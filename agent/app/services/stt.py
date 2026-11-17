"""Speech to text with automatic fallback: Groq key pool (fast, free tier) -> OpenAI -> local faster-whisper."""
from __future__ import annotations

import asyncio
import io
import logging
import math
import time
import wave
from dataclasses import dataclass

import httpx
import numpy as np

from app.config import Settings
from app.services.routing import Route, classify_exception, classify_status, record_failure, rotate_groups, snapshot

log = logging.getLogger("stt")

SAMPLE_RATE = 16000

# Whisper is known to "hear" these when given near-silence or noise.
_HALLUCINATIONS = {
    "you", "thank you", "thanks", "thanks for watching", "thank you for watching", "bye", "bye bye",
    "subtitles by the amara.org community", "so", "okay", "uh", "um", "hmm", "mm", "mhm",
}


@dataclass
class STTResult:
    text: str
    language: str | None
    ms: int
    ignored: str | None = None  # too_short | silent | no_speech | hallucination | error
    route: str | None = None


def pcm_to_wav(pcm: bytes, sr: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def looks_like_hallucination(text: str, duration_s: float, rms: float) -> bool:
    t = "".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").strip()
    if not t:
        return True
    if t in _HALLUCINATIONS and (duration_s < 1.6 or rms < 400):
        return True
    return False


class STT:
    def __init__(self, settings: Settings):
        self.s = settings
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0), limits=httpx.Limits(max_keepalive_connections=10))
        self.routes = self._build_routes()
        self._rr = 0
        self.last_error: str | None = None
        self.last_route: str | None = None
        self._local = None
        self._local_lock = asyncio.Semaphore(1)  # one CPU transcription at a time
        self.provider = settings.stt_route_order  # for display

    def _build_routes(self) -> list[Route]:
        s, routes = self.s, []
        for prov in (p.strip() for p in s.stt_route_order.split(",")):
            if prov == "groq":
                for i, k in enumerate(s.groq_keys):
                    routes.append(Route(f"groq#{i + 1}/{s.groq_stt_model}", "groq", k, s.groq_stt_model))
            elif prov == "openai" and s.openai_api_key:
                routes.append(Route(f"openai/{s.stt_model}", "openai", s.openai_api_key, s.stt_model))
            elif prov == "local":
                routes.append(Route(f"local/{s.local_stt_model}", "local", "", s.local_stt_model))
        return routes

    @property
    def enabled(self) -> bool:
        return any(not r.disabled for r in self.routes)

    @property
    def model(self) -> str:
        return self.last_route or (self.routes[0].name if self.routes else "none")

    def status(self) -> list[dict]:
        return snapshot(self.routes)

    # ------------------------------------------------------------------ main
    async def transcribe(self, pcm: bytes) -> STTResult:
        t0 = time.perf_counter()
        samples = np.frombuffer(pcm, dtype=np.int16)
        dur = len(samples) / SAMPLE_RATE
        if dur < 0.35:
            return STTResult("", None, 0, ignored="too_short")
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if len(samples) else 0.0
        if rms < 80:
            return STTResult("", None, 0, ignored="silent")

        wav = pcm_to_wav(pcm)
        self._rr += 1
        for r in [x for x in rotate_groups(self.routes, self._rr) if x.available()]:
            try:
                if r.provider == "local":
                    text, lang, no_speech = await self._local_transcribe(r, samples)
                else:
                    text, lang, no_speech = await self._http_transcribe(r, wav)
            except asyncio.CancelledError:
                raise
            except _RouteError as e:
                record_failure(r, self.routes, e.kind, e.cooldown)
                self.last_error = f"{r.name}: {e.kind}"
                continue
            except Exception as e:
                kind, cd = classify_exception(e)
                record_failure(r, self.routes, kind, cd)
                self.last_error = f"{r.name}: {kind}"
                continue
            r.ok_count += 1
            self.last_route, self.last_error = r.name, None
            ms = int((time.perf_counter() - t0) * 1000)
            text = text.strip()
            if no_speech:
                return STTResult("", lang, ms, ignored="no_speech", route=r.name)
            if looks_like_hallucination(text, dur, rms):
                return STTResult("", lang, ms, ignored="hallucination", route=r.name)
            return STTResult(text, lang, ms, route=r.name)
        return STTResult("", None, int((time.perf_counter() - t0) * 1000), ignored="error")

    # ------------------------------------------------------------------ providers
    async def _http_transcribe(self, r: Route, wav: bytes) -> tuple[str, str | None, bool]:
        if r.provider == "groq":
            url, data = "https://api.groq.com/openai/v1/audio/transcriptions", {"model": r.model, "response_format": "verbose_json", "temperature": "0"}
        else:
            url, data = "https://api.openai.com/v1/audio/transcriptions", {"model": r.model}
        resp = await self.http.post(url, headers={"Authorization": f"Bearer {r.key}"}, files={"file": ("speech.wav", wav, "audio/wav")}, data=data)
        if resp.status_code != 200:
            # OpenAI: retry once with the older model if the new one is unavailable on this account
            if r.provider == "openai" and resp.status_code in (400, 404) and r.model != self.s.stt_fallback_model:
                r.model = self.s.stt_fallback_model
                return await self._http_transcribe(r, wav)
            kind, cd = classify_status(resp.status_code, resp.headers)
            raise _RouteError(kind, cd)
        j = resp.json()
        lang = j.get("language") or (j.get("languages") or [None])[0]
        segs = j.get("segments") or []
        no_speech = bool(segs) and all(float(s.get("no_speech_prob", 0)) > 0.8 and float(s.get("avg_logprob", 0)) < -1.0 for s in segs)
        return j.get("text", ""), lang, no_speech

    def _load_local(self, model: str):
        if self._local is None:
            from faster_whisper import WhisperModel  # optional dependency (build arg WITH_LOCAL_STT=1)

            self._local = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=4, download_root=f"{self.s.data_dir}/models")
        return self._local

    async def warm(self) -> None:
        """Validate cloud keys once, and pre-load the local model only if it is the sole route."""
        seen: set[tuple[str, str]] = set()
        for r in list(self.routes):
            if r.provider == "local" or (r.provider, r.key) in seen:
                continue
            seen.add((r.provider, r.key))
            base = "https://api.groq.com/openai/v1" if r.provider == "groq" else "https://api.openai.com/v1"
            try:
                resp = await self.http.get(f"{base}/models", headers={"Authorization": f"Bearer {r.key}"}, timeout=6)
                if resp.status_code != 200:
                    kind, cd = classify_status(resp.status_code, resp.headers)
                    record_failure(r, self.routes, kind, cd)
            except Exception as e:
                kind, cd = classify_exception(e)
                record_failure(r, self.routes, kind, cd)
        local = next((r for r in self.routes if r.provider == "local"), None)
        cloud_ok = any(r.provider != "local" and not r.disabled for r in self.routes)
        if local and not cloud_ok:  # nothing else works: be ready
            await asyncio.to_thread(self._load_local, local.model)
        log.info("stt routes: %s", [f"{x['route']}={x['state']}" for x in self.status()])

    async def _local_transcribe(self, r: Route, samples: np.ndarray) -> tuple[str, str | None, bool]:
        def run() -> tuple[str, str | None, bool]:
            model = self._load_local(r.model)
            audio = samples.astype(np.float32) / 32768.0
            segs, info = model.transcribe(audio, beam_size=1, vad_filter=False, condition_on_previous_text=False, temperature=0.0)
            segs = list(segs)
            no_speech = bool(segs) and all(s.no_speech_prob > 0.8 and s.avg_logprob < -1.0 for s in segs)
            return " ".join(x.text for x in segs), info.language, no_speech

        async with self._local_lock:
            return await asyncio.to_thread(run)


class _RouteError(Exception):
    def __init__(self, kind: str, cooldown: float):
        super().__init__(kind)
        self.kind, self.cooldown = kind, cooldown
