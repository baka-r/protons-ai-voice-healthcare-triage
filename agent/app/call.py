"""One live call (one browser WebSocket): audio in -> STT -> engine -> TTS audio out."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from app.config import Settings
from app.db import Store
from app.dialog.engine import Engine
from app.dialog.session import HandoverRequest, Line, Reply, Session
from app.hub import Hub
from app.safety import scripts
from app.safety.guard import check_output
from app.safety.pii import mask
from app.services.emr import EMR
from app.services.llm import LLM
from app.services.rag import RAG
from app.metrics import metrics
from app.services.lang import Localizer
from app.services.stt import STT, STTResult, script_of
from app.safety.text import normalize
from app.dialog import rules
from app.services.tts import PAUSE_LINE_MS, SAMPLE_RATE, TTS, pause_ms, silence, split_sentences

log = logging.getLogger("call")


@dataclass
class Deps:
    settings: Settings
    llm: LLM
    stt: STT
    tts: TTS
    emr: EMR
    rag: RAG
    engine: Engine
    store: Store
    hub: Hub
    loc: Localizer


class CallSession:
    def __init__(self, ws: WebSocket, deps: Deps, ip: str = "unknown"):
        self.ws = ws
        self.d = deps
        self.s = Session(id=uuid.uuid4().hex[:12], client_ip=ip)
        self.inflight = 0
        self.turn_task: asyncio.Task | None = None
        self.skip_wait_line = False
        self._last_text = ""
        self.turn_lock = asyncio.Lock()
        self.speak_lock = asyncio.Lock()
        self.speak_task: asyncio.Task | None = None
        self.hold_task: asyncio.Task | None = None
        self.bg: set[asyncio.Task] = set()
        self.mode = "normal"  # normal | handover | emergency | connected
        self.protect_speech = False
        self.closed = False
        self.stt_failures = 0
        self._timing: dict[str, Any] | None = None

    # ------------------------------------------------------------------ plumbing
    async def send(self, obj: dict) -> None:
        if self.closed:
            return
        try:
            await self.ws.send_text(json.dumps(obj, ensure_ascii=False, default=str))
        except Exception:
            self.closed = True

    async def send_bytes(self, data: bytes) -> None:
        if self.closed:
            raise asyncio.CancelledError
        try:
            await self.ws.send_bytes(data)
        except Exception:
            self.closed = True
            raise asyncio.CancelledError

    async def state(self, st: str) -> None:
        await self.send({"type": "state", "state": st, "mode": self.mode})

    async def trace(self, step: str, status: str, detail: str = "") -> None:
        await self.send({"type": "trace", "step": step, "status": status, "detail": detail, "t": time.time()})

    def _spawn(self, coro) -> None:
        t = asyncio.get_running_loop().create_task(coro)
        self.bg.add(t)
        t.add_done_callback(self.bg.discard)

    def _mask(self, text: str) -> str:
        """Mask phone/CNIC/email/dates plus the caller's own name (once known) before storing or showing staff."""
        out = mask(text)
        names = []
        if self.s.claimed_name:
            names += self.s.claimed_name.split()
        if self.s.patient:
            names += self.s.patient["name"].split()
        for n in {n for n in names if len(n) >= 3}:
            out = re.sub(rf"\b{re.escape(n)}\b", "[NAME]", out, flags=re.I)
        return out

    def _remember(self, role: str, text: str) -> None:
        self.s.history.append({"role": role, "text": text, "ts": time.time()})

    # ------------------------------------------------------------------ lifecycle
    async def start(self, lang: str = "en") -> None:
        d, s = self.d, self.s
        if lang in ("hi", "ur"):
            s.language = lang
            await self.send({"type": "language", "lang": lang})
        d.hub.calls[s.id] = self
        d.store.fire(d.store.create_session, s.id)
        d.store.fire(d.store.audit, "system", "call_started", {"session": s.id})
        await self.send({
            "type": "session", "id": s.id, "hospital": d.settings.hospital_name,
            "assistant": d.settings.assistant_name, "emergency": d.settings.emergency_number,
        })
        await self.send({"type": "safety", "items": {
            "redflag": "ok", "scope": "ok", "pii": "on", "llm_check": "ok" if d.llm.enabled else "offline"}})
        await self.state("speaking")
        self._timing = {"t0": time.perf_counter()}
        await self._speak([Line(text=scripts.fixed("greeting"), key="greeting")], self._timing)
        self._remember("assistant", scripts.fixed("greeting"))
        await self.state("listening")
        self._spawn(self.d.llm.warm())

    async def close(self) -> None:
        if self.closed and self.s.ended:
            return
        self.closed = True
        self.s.ended = True
        for t in list(self.bg) + [self.speak_task, self.hold_task]:
            if t and not t.done():
                t.cancel()
        d, s = self.d, self.s
        d.hub.calls.pop(s.id, None)
        outcome = "handover" if s.handover_id else "completed"
        emr_id = s.patient["id"] if s.patient else None
        d.store.fire(d.store.end_session, s.id, outcome, s.turns, s.language, emr_id)
        d.store.fire(d.store.audit, "system", "call_ended", {"session": s.id, "outcome": outcome})
        h = d.hub.handovers.get(s.handover_id or "")
        if h and h["status"] in ("waiting",):
            h["status"] = "abandoned"
            await d.hub.broadcast_staff({"type": "handover_updated", "handover": d.hub.public(h)})

    # ------------------------------------------------------------------ speaking
    async def _speak(self, lines: list[Line], timing: dict | None = None) -> None:
        async with self.speak_lock:
            task = asyncio.get_running_loop().create_task(self._speak_inner(lines, timing))
            self.speak_task = task
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                task.cancel()
                raise
            finally:
                self.speak_task = None
            if not task.cancelled() and task.exception():
                log.error("speak failed: %r", task.exception())

    async def _localize(self, line: Line, text: str) -> tuple[str, str | None]:
        """(text to show and speak, voice). English stays as is; Hindi/Urdu callers get the translated line in a Hindi voice."""
        if self.s.language == "en":
            return text, None
        loc = self.d.loc
        out = await loc.text(text, self.s.language, line.key if text == line.text else None)
        if out is None:  # translation unavailable: speak English rather than nothing
            return text, None
        return out, loc.voice(self.s.language)

    async def _speak_inner(self, lines: list[Line], timing: dict | None) -> None:
        await self.state("speaking")
        started = False
        loop = asyncio.get_running_loop()
        # 1) safety guard on the ENGLISH text, always. 2) translate (concurrently) for Hindi/Urdu callers.
        texts: list[str] = []
        for line in lines:
            text = line.text
            if not line.trusted:
                verdict = check_output(text)
                if not verdict.ok:
                    self.d.store.fire(self.d.store.audit, "system", "output_guard_block", {"session": self.s.id, "reason": verdict.reason})
                    text = scripts.fixed("degraded")
            texts.append(text)
        loc_tasks = [loop.create_task(self._localize(line, t)) for line, t in zip(lines, texts)]
        try:
            for line, english, task in zip(lines, texts, loc_tasks):
                text, voice = await task
                await self.send({"type": "caption", "role": "assistant", "text": text})
                if not started:
                    await self.send({"type": "audio_start", "sample_rate": SAMPLE_RATE})
                    started = True
                else:
                    await self.send_bytes(silence(PAUSE_LINE_MS))  # breath between separate lines
                try:
                    await self._send_audio(text, timing, line.chunks if (voice is None and english == line.text) else None, voice)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("tts failed (%s) - caption only", type(e).__name__)
                    await self.send({"type": "error", "where": "tts", "message": "Voice unavailable - showing text only"})
        finally:
            for t in loc_tasks:
                if not t.done():
                    t.cancel()
            if started:
                await self.send({"type": "audio_end"})

    async def _first_audio(self, timing: dict | None) -> None:
        if timing is not None and "first_audio" not in timing:
            now = time.perf_counter()
            timing["first_audio"] = now
            metrics.observe("first_audio", (now - timing["t0"]) * 1000)
            await self.send({"type": "timing", **{
                "stt_ms": timing.get("stt_ms"), "nlu_ms": timing.get("nlu_ms"),
                "tts_first_ms": int((now - timing.get("tts_t0", timing["t0"])) * 1000),
                "server_ms": int((now - timing["t0"]) * 1000),
            }})

    async def _send_pcm(self, pcm: bytes, timing: dict | None) -> None:
        await self._first_audio(timing)
        for j in range(0, len(pcm), 16384):
            await self.send_bytes(pcm[j:j + 16384])
            await asyncio.sleep(0)

    async def _send_audio(self, text: str, timing: dict | None, chunks: list[str] | None = None, voice: str | None = None) -> None:
        """Whole line cached -> play at once. Otherwise speak it chunk by chunk: cached chunks play instantly, the first
        uncached one streams as it is synthesised, and the rest are synthesised in the background (2 at a time)."""
        tts = self.d.tts
        if timing is not None:
            timing["tts_t0"] = time.perf_counter()
        pcm = tts.cached(text, voice)
        if pcm is not None:
            await self._send_pcm(pcm, timing)
            return
        parts = chunks or split_sentences(text)
        tasks: dict[int, asyncio.Task] = {}
        loop = asyncio.get_running_loop()

        async def pause_before(i: int) -> None:
            """Natural, deliberate gap between pieces (the pieces themselves are silence-trimmed)."""
            if i > 0:
                await self.send_bytes(silence(pause_ms(parts[i - 1])))

        def prepare_next(i: int) -> None:  # synthesise the next uncached chunks while earlier audio is still playing
            for k in range(i + 1, min(i + 3, len(parts))):
                if k not in tasks and tts.cached(parts[k], voice) is None:
                    tasks[k] = loop.create_task(tts.render(parts[k], voice=voice))

        try:
            for i, part in enumerate(parts):
                hit = tts.cached(part, voice)
                if hit is not None:
                    prepare_next(i)  # playback of cached audio gives the engine time to prepare what follows
                    await pause_before(i)
                    await self._send_pcm(hit, timing)
                elif i in tasks:
                    prepare_next(i)
                    data = await tasks[i]
                    await pause_before(i)
                    await self._send_pcm(data, timing)
                else:  # uncached: queue the following sentences right behind it (the engine does one at a time, in order)
                    prepare_next(i)
                    await pause_before(i)
                    async for chunk in tts.stream_shared(part, voice):
                        await self._first_audio(timing)
                        for j in range(0, len(chunk), 16384):
                            await self.send_bytes(chunk[j:j + 16384])
        finally:
            for t in tasks.values():
                if not t.done():
                    t.cancel()

    # ------------------------------------------------------------------ input
    async def handle_barge_in(self) -> None:
        if self.protect_speech:
            return
        if self.speak_task and not self.speak_task.done():
            self.speak_task.cancel()
        await self.send({"type": "audio_end", "interrupted": True})
        if self.mode in ("normal",) and not self.s.ended:
            await self.state("listening")

    async def handle_input(self, pcm: bytes | None = None, text: str | None = None) -> None:
        if self.s.ended or self.mode == "connected":
            return
        me = asyncio.current_task()
        # A new message SUPERSEDES whatever Hania is still doing (thinking or speaking): never finish the old answer first.
        # Emergency / hand-over speech is protected and never cut off.
        if self.mode == "normal" and not self.protect_speech:
            prev = self.turn_task
            if prev is not None and prev is not me and not prev.done():
                prev.cancel()
                metrics.inc("turns_superseded")
            if self.speak_task and not self.speak_task.done():
                self.speak_task.cancel()
            await self.send({"type": "audio_end", "interrupted": True})
        elif self.mode == "handover" and not self.protect_speech:
            # speaking over the "connecting you to staff" lines: stop them at once (the hand-over itself is NOT cancelled by this)
            self.skip_wait_line = True
            if self.speak_task and not self.speak_task.done():
                self.speak_task.cancel()
            await self.send({"type": "audio_end", "interrupted": True})
        self.turn_task = me
        self.inflight += 1
        try:
            async with self.turn_lock:
                try:
                    metrics.inc("turns_total")
                    await self._turn(pcm, text)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("turn failed - failing closed")
                    metrics.inc("turn_errors")
                    if self.mode == "normal":
                        reply = Reply(lines=[Line(text=scripts.fixed("degraded"), key="degraded")], state="HANDOVER",
                                      handover=HandoverRequest("degraded", "routine", source="system"))
                        await self._deliver(reply, {"t0": time.perf_counter()})
        finally:
            self.inflight -= 1

    async def _turn(self, pcm: bytes | None, text: str | None) -> None:
        s, d = self.s, self.d
        timing: dict[str, Any] = {"t0": time.perf_counter()}
        self._timing = timing
        if self.mode in ("handover", "emergency"):
            await self._turn_during_handover(pcm, text)
            return

        await self.state("thinking")
        filler_task: asyncio.Task | None = None
        filler_started = False

        async def filler() -> None:
            # Only starts once speech recognition is done: it bridges a slow ENGINE (e.g. the AI call), never an instant answer.
            nonlocal filler_started
            await asyncio.sleep(d.settings.filler_after_ms / 1000)
            filler_started = True
            await self._speak([Line(text=scripts.fixed("filler"), key="filler")])

        try:
            if pcm is not None:
                await self.trace("listen", "ok", f"{len(pcm) / 32000:.1f}s of speech")
                await self.trace("transcribe", "run", "speech to text")
                try:
                    r = await asyncio.wait_for(d.stt.transcribe(pcm, self._stt_hint()), 14)
                except asyncio.TimeoutError:
                    r = STTResult("", None, 14000, ignored="error")
                timing["stt_ms"] = r.ms
                metrics.observe("stt", r.ms)
                if r.ignored in ("too_short", "silent"):
                    await self.trace("transcribe", "skip", f"ignored ({r.ignored})")
                    await self.state("listening")
                    return
                if r.ignored == "error" or not r.text:
                    self.stt_failures += 1
                    await self.trace("transcribe", "alert", "could not transcribe")
                    text = ""
                else:
                    self.stt_failures = 0
                    text = r.text
                    await self.trace("transcribe", "ok", f"{r.ms} ms")
                if r.ignored == "error" and self.stt_failures >= 2:
                    reply = Reply(lines=[Line(text=scripts.fixed("degraded"), key="degraded")], state="HANDOVER",
                                  handover=HandoverRequest("degraded", "routine", source="system"))
                    await self._finish_turn(reply, timing, filler_task, filler_started)
                    return
            text = (text or "").strip()
            await self._maybe_switch_language(text)
            state_before = s.state
            identity = state_before in ("AWAIT_NAME", "AWAIT_DOB")
            self._last_text = text
            if text:
                await self.send({"type": "caption", "role": "caller", "text": text})
                self._remember("caller", "[identity details provided]" if identity else self._mask(text))
            await self.trace("safety", "run", "red-flag scan + scope check")
            filler_task = asyncio.get_running_loop().create_task(filler())
            try:
                reply = await asyncio.wait_for(d.engine.handle(s, text), d.settings.turn_deadline_s)
            except asyncio.TimeoutError:
                log.error("engine exceeded %ss - failing closed", d.settings.turn_deadline_s)
                metrics.inc("turn_timeouts")
                s.state = "HANDOVER"
                reply = Reply(lines=[Line(text=scripts.fixed("degraded"), key="degraded")], state="HANDOVER",
                              handover=HandoverRequest("degraded", "routine", source="system"),
                              trace=[{"step": "route", "status": "alert", "detail": "processing timed out - handing over"}])
            timing["nlu_ms"] = reply.nlu_ms
            metrics.observe("nlu", reply.nlu_ms)
            d.store.fire(d.store.add_utterance, s.id, "caller",
                         "[identity details provided]" if identity else self._mask(text),
                         reply.intent, {"stt_ms": timing.get("stt_ms"), "nlu_ms": reply.nlu_ms})
        except BaseException:
            if filler_task and not filler_task.done():
                filler_task.cancel()
            raise
        await self._finish_turn(reply, timing, filler_task, filler_started)

    async def _finish_turn(self, reply: Reply, timing: dict, filler_task: asyncio.Task | None, filler_started: bool) -> None:
        if filler_task:
            if not filler_started:
                filler_task.cancel()
            else:
                try:
                    await filler_task
                except asyncio.CancelledError:
                    pass
        await self._deliver(reply, timing)

    # ------------------------------------------------------------------ language
    def _stt_hint(self) -> str | None:
        """English sessions auto-detect (so Hindi/Urdu is noticed); Hindi/Urdu sessions hint their language, except for names."""
        lang = self.s.language
        if lang == "en":
            return None
        return "en" if self.s.state == "AWAIT_NAME" else lang

    async def set_language(self, lang: str) -> None:
        if lang not in ("en", "hi", "ur") or lang == self.s.language:
            return
        self.s.language = lang
        await self.send({"type": "language", "lang": lang})
        await self.trace("understand", "ok", f"language set to {lang}")
        if lang != "en" and self.d.tts is not None:  # make sure the Hindi greeting-style lines are ready
            self._spawn(self.d.tts.warm_voice(self.d.loc.hindi_fixed_lines(), self.d.loc.voice(lang)))

    async def _maybe_switch_language(self, text: str) -> None:
        """Heard (or typed) Hindi/Urdu while the session is English -> switch automatically, and tell the UI."""
        if self.s.language != "en" or not text:
            return
        sc = script_of(text)
        if sc == "deva":
            await self.set_language("hi")
        elif sc == "arab":
            await self.set_language("ur")

    # ------------------------------------------------------------------ cancelling a hand-over
    async def _cancel_handover(self) -> None:
        """Caller says they do NOT want staff: switch back to the assistant and carry on talking.
        A routine/urgent hand-over is withdrawn. An EMERGENCY alert stays active for safety (never silently cancelled),
        but Hania keeps talking with the caller."""
        s, d = self.s, self.d
        h = d.hub.handovers.get(s.handover_id or "")
        keep = bool(h and h["urgency"] == "emergency")
        if self.hold_task:
            self.hold_task.cancel()
        self.mode = "normal"
        self.protect_speech = False
        s.state = "IDLE"
        s.unclear = 0
        if keep:
            key = "handover_keep_alert"
            d.store.fire(d.store.audit, "caller", "handover_cancel_refused_emergency", {"session": s.id, "handover": s.handover_id})
        else:
            key = "handover_cancelled"
            if h and h["status"] == "waiting":
                h["status"] = "cancelled"
                d.store.fire(d.store.update_escalation, h["id"], status="cancelled")
                await d.hub.broadcast_staff({"type": "handover_updated", "handover": d.hub.public(h)})
            d.store.fire(d.store.audit, "caller", "handover_cancelled", {"session": s.id, "handover": s.handover_id})
            s.handover_id = None
            await self.send({"type": "handover", "status": "cancelled"})
            metrics.inc("handovers_cancelled")
        await self._speak([Line(text=scripts.fixed(key), key=key)])
        self._remember("assistant", scripts.fixed(key))
        await self.state("listening")

    async def _turn_during_handover(self, pcm: bytes | None, text: str | None) -> None:
        """While waiting for staff the assistant stays quiet but keeps a transcript for them - unless the caller
        says they don't want staff, in which case she switches back and carries on."""
        if pcm is not None:
            r = await self.d.stt.transcribe(pcm, self._stt_hint())
            text = r.text
        text = (text or "").strip()
        if not text:
            return
        await self.send({"type": "caption", "role": "caller", "text": text})
        if rules.wants_cancel_handover(normalize(text)):
            self._remember("caller", self._mask(text))
            await self._cancel_handover()
            return
        self._remember("caller", self._mask(text))
        h = self.d.hub.handovers.get(self.s.handover_id or "")
        if h:
            h["transcript"] = list(self.s.history)
            await self.d.hub.broadcast_staff({"type": "handover_updated", "handover": self.d.hub.public(h)})

    # ------------------------------------------------------------------ delivery
    async def _deliver(self, reply: Reply, timing: dict) -> None:
        s, d = self.s, self.d
        for ev in reply.trace:
            await self.send({"type": "trace", **ev, "t": time.time()})
        if reply.safety:
            await self.send({"type": "safety", "items": reply.safety})
        if reply.sources:
            await self.send({"type": "sources", "items": reply.sources})
        if reply.intent:
            await self.send({"type": "intent", "intent": reply.intent})
        for line in reply.lines:
            self._remember("assistant", line.text)
        spoken = " ".join(x.text for x in reply.lines)[:2000]
        if reply.sources:
            d.store.fire(d.store.add_utterance_with_sources, s.id, spoken, reply.intent, reply.sources)
            d.store.fire(d.store.audit, "system", "approved_document_used",
                         {"session": s.id, "chunks": [x["chunk_id"] for x in reply.sources]})
        else:
            d.store.fire(d.store.add_utterance, s.id, "assistant", spoken, reply.intent, None)
        if reply.event:
            ev = reply.event
            if ev["type"] == "appointment_booked" and s.patient:
                d.store.fire(d.store.add_appointment, s.patient["id"], ev["appointment"])
                d.store.fire(d.store.audit, "caller", "appointment_booked", {"session": s.id, "appointment": ev["appointment"]["id"]})
            elif ev["type"] == "symptom_guidance":
                metrics.inc("symptom_guidance_given")
                d.store.fire(d.store.audit, "system", "symptom_guidance_given", {"session": s.id, "chunk": ev["chunk"]})
            elif ev["type"] == "appointment_cancelled":
                d.store.fire(d.store.set_appointment_status, ev["appointment"]["id"], "cancelled")
                d.store.fire(d.store.audit, "caller", "appointment_cancelled", {"session": s.id, "appointment": ev["appointment"]["id"]})
        if reply.pending_analysis is not None:
            self._spawn(self._late_check(reply.pending_analysis, self._last_text))
        if reply.handover:
            await self._begin_handover(reply.handover)
            self.protect_speech = reply.handover.urgency == "emergency"
        self.skip_wait_line = False
        try:
            await self._speak(reply.lines, timing)
            if reply.handover and not self.skip_wait_line:
                await self._speak([Line(text=scripts.fixed("handover_wait"), key="handover_wait")])
        finally:
            self.protect_speech = False
        if reply.handover and self.mode == "normal":
            pass  # the caller already cancelled it while the line was playing
        elif reply.handover:
            self.hold_task = asyncio.get_running_loop().create_task(self._hold(reply.handover.urgency))
            await self.state("handover")
        elif reply.end:
            s.ended = True
            await self.state("ended")
            await self.send({"type": "ended"})
        elif self.mode == "normal":
            await self.state("listening")

    async def _late_check(self, task: asyncio.Task, text: str) -> None:
        """The AI safety net finished after a benign reply was already spoken: interrupt and escalate if it disagrees."""
        try:
            a = await task
        except asyncio.CancelledError:
            return
        except Exception:
            a = None
        if self.closed or self.s.ended or self.mode != "normal":
            return
        action = self.d.engine.late_action(self.s, a, text)
        if action is None:
            await self.send({"type": "safety", "items": {"llm_check": "ok" if a is not None else "offline"}})
            return
        metrics.inc("late_escalations", kind=action.handover.reason if action.handover else "none")
        log.warning("parallel AI check escalated an already-answered turn (%s)", action.handover.reason if action.handover else "?")
        if self.speak_task and not self.speak_task.done():
            self.speak_task.cancel()
        await self.send({"type": "audio_end", "interrupted": True})
        self.s.state = "HANDOVER"
        await self._deliver(action, {"t0": time.perf_counter()})  # deliberately not behind the turn lock: must interrupt now

    # ------------------------------------------------------------------ hand-over (simulated)
    async def _begin_handover(self, req: HandoverRequest) -> None:
        s, d = self.s, self.d
        if s.handover_id:
            # an alert is already open (e.g. an emergency the caller asked not to cancel): re-enter hand-over mode, no duplicate
            h0 = d.hub.handovers.get(s.handover_id)
            if h0 and h0["status"] == "waiting":
                self.mode = "emergency" if h0["urgency"] == "emergency" else "handover"
                await self.send({"type": "handover", "status": "waiting", "id": h0["id"], "reason": h0["reason"], "urgency": h0["urgency"]})
            return
        self.mode = "emergency" if req.urgency == "emergency" else "handover"
        metrics.inc("handovers_total", reason=req.reason, urgency=req.urgency)
        h = d.hub.create_handover(s.id, req.reason, req.urgency, req.category, req.source, s.history)
        s.handover_id = h["id"]
        d.store.fire(d.store.create_escalation, h["id"], s.id, req.reason, req.urgency, req.category, req.source)
        d.store.fire(d.store.audit, "system", "handover_created",
                     {"session": s.id, "handover": h["id"], "reason": req.reason, "urgency": req.urgency, "category": req.category, "source": req.source})
        await self.send({"type": "handover", "status": "waiting", "id": h["id"], "reason": req.reason, "urgency": req.urgency})
        await d.hub.broadcast_staff({"type": "handover_created", "handover": d.hub.public(h)})
        self._spawn(self._summarize(h))

    async def _summarize(self, h: dict) -> None:
        d = self.d
        summary = await d.llm.summarize(h["transcript"], h["reason"])
        if not summary:
            summary = {
                "summary": f"Call handed over (reason: {h['reason']}). Automatic summary unavailable.",
                "caller_request": "", "urgency": h["urgency"], "notes_for_staff": "",
            }
        h["summary"] = summary
        d.store.fire(d.store.update_escalation, h["id"], summary=summary)
        await d.hub.broadcast_staff({"type": "handover_updated", "handover": d.hub.public(h)})

    async def _hold(self, urgency: str) -> None:
        try:
            await asyncio.sleep(30)
            h = self.d.hub.handovers.get(self.s.handover_id or "")
            if h and h["status"] == "waiting" and not self.closed:
                await self._speak([Line(text=scripts.fixed("still_waiting"), key="still_waiting")])
                await self.state("handover")
        except asyncio.CancelledError:
            pass

    async def on_staff_accepted(self, staff_name: str) -> None:
        if self.hold_task:
            self.hold_task.cancel()
        self.mode = "connected"
        self.protect_speech = False
        if self.speak_task and not self.speak_task.done():
            self.speak_task.cancel()
        await self.send({"type": "handover", "status": "connected", "staff": staff_name, "id": self.s.handover_id})
        await self.state("connected")
        self._spawn(self._speak([Line(text=scripts.fixed("connected"), key="connected")]))

    async def request_human(self) -> None:
        if self.s.ended or self.mode in ("handover", "emergency", "connected"):
            return
        async with self.turn_lock:
            reply = Reply(
                lines=[Line(text=scripts.fixed("human_request"), key="human_request")], state="HANDOVER",
                handover=HandoverRequest("caller_requested", "routine", source="caller"),
                trace=[{"step": "route", "status": "ok", "detail": "caller pressed 'Talk to a person'"}],
            )
            self.s.state = "HANDOVER"
            await self._deliver(reply, {"t0": time.perf_counter()})
