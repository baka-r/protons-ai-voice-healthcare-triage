from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from app.call import CallSession, Deps
from app.config import get_settings
from app.db import Store
from app.dialog.engine import Engine
from app.hub import Hub
from app.logging_setup import setup_logging
from app.metrics import metrics
from app.safety import scripts
from app.security import SlidingWindow, Tokens, check_production_config, client_ip, origin_allowed, pin_ok, require_staff
from app.services.emr import EMR
from app.services.llm import LLM
from app.services.rag import RAG
from app.services.stt import STT
from app.services.tts import TTS

setup_logging()
log = logging.getLogger("main")

deps: Deps
tokens: Tokens
login_failures = SlidingWindow(5, 900)  # 5 bad PINs / 15 min / IP
new_calls = SlidingWindow(12, 60)  # 12 new calls / min / IP
ip_active: dict[str, int] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global deps, tokens
    s = get_settings()
    if s.app_env == "prod":
        problems = check_production_config(s)
        if problems:
            raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    elif s.staff_pin in ("1234", ""):
        log.warning("STAFF_PIN is a weak demo value - acceptable for dev only (APP_ENV=prod refuses to start)")
    tokens = Tokens(s.secret_key, s.staff_token_ttl_s)
    store = Store(s.database_url)
    await asyncio.to_thread(store.init)
    llm, stt, tts, emr, rag = LLM(s), STT(s), TTS(s), EMR(s), RAG(s)
    verify_limiter = SlidingWindow(8, 3600)  # 8 failed identity checks / hour / IP
    from app.services.doctor import Doctor
    from app.services.medsearch import MedSearch

    doctor = Doctor(s, llm, MedSearch())
    deps = Deps(settings=s, llm=llm, stt=stt, tts=tts, emr=emr, rag=rag,
                engine=Engine(s, llm, emr, rag, verify_limiter, doctor), store=store, hub=Hub())

    async def init_rag() -> None:
        docs = await rag.init(date.today())
        if docs:
            store.fire(store.record_knowledge, docs)

    async def warm_dateparser() -> None:
        from app.dialog import rules
        await asyncio.to_thread(rules.parse_date, "tomorrow")
        await asyncio.to_thread(rules.parse_dob, "12 March 1990")

    async def warm_phrases() -> None:
        """After the fixed scripts: pre-render the reusable booking phrases (dates, times, departments) so slot offers are instant."""
        from app.dialog.engine import phrase_vocab

        while not tts.ready:
            await asyncio.sleep(2)
        try:
            depts = [d["name"] for d in await emr.departments()]
        except Exception:
            return
        vocab = phrase_vocab(depts)
        done = 0
        for text in vocab:
            if tts.cached(text) is None:
                try:
                    await tts.render(text, fixed=True)
                except Exception:
                    await asyncio.sleep(3)
                    continue
            done += 1
        log.info("tts phrase cache ready: %d/%d booking phrases", done, len(vocab))
        # approved guidance + information passages are spoken sentence by sentence: pre-render those too
        from app.services.tts import split_sentences

        while not rag.ready:
            await asyncio.sleep(3)
        parts = [p for dv in rag.docs if dv.included for _h, text in dv.chunks for p in split_sentences(text)]
        for p in dict.fromkeys(parts):
            if tts.cached(p) is None:
                try:
                    await tts.render(p, fixed=True)
                except Exception:
                    await asyncio.sleep(3)
        log.info("tts knowledge cache ready: %d approved sentences", len(set(parts)))

    tasks = [
        asyncio.create_task(tts.warm(scripts.all_fixed())),
        asyncio.create_task(warm_phrases()),
        asyncio.create_task(llm.warm()),
        asyncio.create_task(stt.warm()),
        asyncio.create_task(init_rag()),
        asyncio.create_task(warm_dateparser()),
    ]
    log.info("agent up: env=%s llm_routes=%d stt_routes=%d voice=%s", s.app_env, len(llm.routes), len(stt.routes), s.tts_voice)
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Hania voice assistant", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def no_store(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ------------------------------------------------------------------ public, non-sensitive
@app.get("/api/health")
async def health():
    """Liveness probe."""
    return {"ok": True}


@app.get("/api/ready")
async def ready(response: Response):
    ok = deps.store.ok and await deps.emr.healthy()
    if not ok:
        response.status_code = 503
    return {"ready": ok}


@app.get("/api/status")
async def status():
    """Booleans only - drives the start screen. No models, keys, errors or provider names."""
    return {
        "llm": deps.llm.enabled, "stt": deps.stt.enabled, "voice": await deps.tts.healthy(), "voice_cache": deps.tts.ready,
        "records": await deps.emr.healthy(), "knowledge": deps.rag.ready, "db": deps.store.ok,
    }


@app.get("/api/config")
async def config():
    s = get_settings()
    return {"hospital": s.hospital_name, "assistant": s.assistant_name, "emergency": s.emergency_number}


# ------------------------------------------------------------------ staff auth
@app.post("/api/staff/login")
async def staff_login(request: Request):
    ip = client_ip(request)
    if login_failures.blocked(ip):
        raise HTTPException(429, "too many attempts, try again later")
    try:
        body = await request.json()
        pin = str(body.get("pin", ""))[:128]
    except Exception:
        raise HTTPException(400, "bad request")
    if not pin_ok(pin, get_settings().staff_pin):
        login_failures.add(ip)
        metrics.inc("staff_login_failed")
        deps.store.fire(deps.store.audit, "staff", "staff_login_failed", {"ip": ip})
        raise HTTPException(401, "wrong PIN")
    deps.store.fire(deps.store.audit, "staff", "staff_login", {"ip": ip})
    return {"token": tokens.issue("staff-demo"), "ttl": get_settings().staff_token_ttl_s}


def _staff(request: Request) -> str:
    return require_staff(request, tokens)


@app.get("/api/staff/handovers")
async def list_handovers(request: Request):
    _staff(request)
    return [deps.hub.public(h, with_transcript=False) for h in sorted(deps.hub.handovers.values(), key=lambda x: -x["created_at"])]


@app.get("/api/staff/handovers/{hid}")
async def get_handover(hid: str, request: Request):
    _staff(request)
    h = deps.hub.handovers.get(hid)
    if not h:
        raise HTTPException(404)
    deps.store.fire(deps.store.audit, "staff", "staff_view_transcript", {"handover": hid}, "staff-demo")
    return deps.hub.public(h)


@app.post("/api/staff/handovers/{hid}/accept")
async def accept_handover(hid: str, request: Request):
    _staff(request)
    h = deps.hub.handovers.get(hid)
    if not h:
        raise HTTPException(404)
    if h["status"] != "waiting":
        raise HTTPException(409, f"handover is {h['status']}")
    name = "Demo Support Agent"
    h["status"], h["accepted_by"], h["accepted_at"] = "connected", name, time.time()
    deps.store.fire(deps.store.update_escalation, hid, status="connected", accepted_by=name)
    deps.store.fire(deps.store.audit, "staff", "handover_accepted", {"handover": hid}, "staff-demo")
    metrics.inc("handover_accepted")
    call = deps.hub.calls.get(h["session_id"])
    if call:
        await call.on_staff_accepted(name)
    await deps.hub.broadcast_staff({"type": "handover_updated", "handover": deps.hub.public(h)})
    return deps.hub.public(h)


@app.post("/api/staff/handovers/{hid}/resolve")
async def resolve_handover(hid: str, request: Request):
    _staff(request)
    h = deps.hub.handovers.get(hid)
    if not h:
        raise HTTPException(404)
    h["status"] = "resolved"
    deps.store.fire(deps.store.update_escalation, hid, status="resolved")
    deps.store.fire(deps.store.audit, "staff", "handover_resolved", {"handover": hid}, "staff-demo")
    await deps.hub.broadcast_staff({"type": "handover_updated", "handover": deps.hub.public(h)})
    return deps.hub.public(h)


@app.get("/api/audit/verify")
async def audit_verify(request: Request):
    _staff(request)
    return await asyncio.to_thread(deps.store.verify_audit)


@app.get("/api/admin/health")
async def admin_health(request: Request):
    _staff(request)
    return {
        "llm_routes": deps.llm.status(), "stt_routes": deps.stt.status(), "llm_last_error": deps.llm.last_error,
        "stt_last_error": deps.stt.last_error, "tts": {"warmed": f"{deps.tts.warm_done}/{deps.tts.warm_total}", "dynamic_cached": len(deps.tts.dynamic)},
        "rag": {"ready": deps.rag.ready, "chunks": deps.rag.chunk_count, "error": deps.rag.error},
        "calls_active": len(deps.hub.calls), "handovers_in_memory": len(deps.hub.handovers),
    }


@app.get("/api/metrics")
async def metrics_endpoint(request: Request):
    _staff(request)
    metrics.gauge("calls_active", len(deps.hub.calls))
    metrics.gauge("handovers_waiting", sum(1 for h in deps.hub.handovers.values() if h["status"] == "waiting"))
    return Response(metrics.render(), media_type="text/plain; version=0.0.4")


# ------------------------------------------------------------------ websockets
@app.websocket("/ws/staff")
async def ws_staff(ws: WebSocket):
    s = get_settings()
    if not origin_allowed(ws, s):
        await ws.close(code=4403)
        return
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), 5))
        if first.get("type") != "auth" or not tokens.verify(first.get("token")):
            await ws.close(code=4401)
            return
    except Exception:
        await ws.close(code=4401)
        return
    deps.hub.staff.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "snapshot", "handovers": [deps.hub.public(h, with_transcript=False) for h in deps.hub.handovers.values()]}, default=str))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        deps.hub.staff.discard(ws)


@app.websocket("/ws/call")
async def ws_call(ws: WebSocket):
    s = get_settings()
    ip = client_ip(ws)
    if not origin_allowed(ws, s):
        await ws.close(code=4403)
        return
    await ws.accept()
    busy = (
        len(deps.hub.calls) >= s.max_concurrent_calls
        or ip_active.get(ip, 0) >= s.max_calls_per_ip
        or not new_calls.allow(ip)
    )
    if busy:
        metrics.inc("calls_rejected")
        await ws.send_text(json.dumps({"type": "error", "where": "capacity", "message": "The line is busy. Please try again in a moment."}))
        await ws.close(code=1013)
        return

    ip_active[ip] = ip_active.get(ip, 0) + 1
    metrics.inc("calls_total")
    call = CallSession(ws, deps, ip)
    tasks: set[asyncio.Task] = set()
    limiter = SlidingWindow(s.max_utterances_per_min, 60)
    activity = {"t": time.monotonic()}
    started = time.monotonic()
    max_bytes = int(s.max_audio_seconds * 16000 * 2)

    def spawn(coro):
        t = asyncio.get_running_loop().create_task(coro)
        tasks.add(t)
        t.add_done_callback(tasks.discard)

    async def watchdog():
        while True:
            await asyncio.sleep(5)
            now = time.monotonic()
            if now - started > s.max_call_seconds or now - activity["t"] > s.idle_timeout_s:
                await call.send({"type": "error", "where": "timeout", "message": "Call ended due to inactivity."})
                await ws.close(code=1000)
                return

    wd = asyncio.get_running_loop().create_task(watchdog())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            activity["t"] = time.monotonic()
            if msg.get("bytes") is not None:
                data = msg["bytes"]
                if len(data) > max_bytes or len(data) % 2 or len(data) < 1000:
                    await call.send({"type": "error", "where": "audio", "message": "Audio rejected"})
                    continue
                if not limiter.allow("utt") or call.inflight >= 3:
                    metrics.inc("utterances_dropped")
                    await call.send({"type": "error", "where": "rate", "message": "Please slow down a little."})
                    continue
                spawn(call.handle_input(pcm=data))
            elif msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                    kind = data.get("type")
                except Exception:
                    continue
                if kind == "start":
                    spawn(call.start())
                elif kind == "text":
                    if not limiter.allow("utt") or call.inflight >= 3:
                        await call.send({"type": "error", "where": "rate", "message": "Please slow down a little."})
                        continue
                    spawn(call.handle_input(text=str(data.get("text", ""))[:500]))
                elif kind == "barge_in":
                    spawn(call.handle_barge_in())
                elif kind == "request_human":
                    spawn(call.request_human())
                elif kind == "end":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        wd.cancel()
        for t in tasks:
            t.cancel()
        ip_active[ip] = max(0, ip_active.get(ip, 1) - 1)
        if ip_active[ip] == 0:
            ip_active.pop(ip, None)
        await call.close()
