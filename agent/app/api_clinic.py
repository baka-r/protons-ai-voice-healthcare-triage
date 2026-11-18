"""Accounts, doctor review, owner dashboard and demo helpers (all staff endpoints are role-checked; see security.ROLES)."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request

from app.demo import SCENARIOS
from app.dialog.triage import TIERS
from app.metrics import metrics
from app.security import ROLES, claims_of, require_role

router = APIRouter()


def _m():
    from app import main  # lazy: main imports this module

    return main


def _who(request: Request, *roles: str) -> dict:
    return require_role(request, _m().tokens, *roles)


# ---------------------------------------------------------------- who am I / accounts (admin)
@router.get("/api/staff/me")
async def me(request: Request):
    return _who(request, "support")


@router.get("/api/admin/accounts")
async def accounts(request: Request):
    _who(request)  # admin only
    return await asyncio.to_thread(_m().deps.store.list_accounts)


@router.post("/api/admin/accounts")
async def create_account(request: Request):
    who = _who(request)
    body = await request.json()
    username = str(body.get("username", "")).strip().lower()
    name = str(body.get("name", "")).strip()
    role = str(body.get("role", ""))
    password = str(body.get("password", ""))
    if not (3 <= len(username) <= 40) or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "username: 3-40 letters, digits, . _ -")
    if role not in ROLES:
        raise HTTPException(400, "role must be support, clinician or admin")
    if len(password) < 10:
        raise HTTPException(400, "password must be at least 10 characters")
    store = _m().deps.store
    if not await asyncio.to_thread(store.create_account, username, name, role, password):
        raise HTTPException(409, "that username already exists")
    store.fire(store.audit, who["user"], "account_created", {"username": username, "role": role})
    return {"ok": True}


@router.post("/api/admin/accounts/{username}")
async def update_account(username: str, request: Request):
    who = _who(request)
    body = await request.json()
    password = body.get("password")
    if password is not None and len(str(password)) < 10:
        raise HTTPException(400, "password must be at least 10 characters")
    if username.lower() == who["user"] and body.get("active") is False:
        raise HTTPException(400, "you cannot deactivate yourself")
    store = _m().deps.store
    if not await asyncio.to_thread(store.set_account, username, body.get("active"), str(password) if password else None):
        raise HTTPException(404)
    store.fire(store.audit, who["user"], "account_updated", {"username": username, "active": body.get("active"), "password_changed": bool(password)})
    return {"ok": True}


# ---------------------------------------------------------------- doctor review (clinician, admin)
@router.get("/api/review/sessions")
async def review_sessions(request: Request, flagged: int = 0):
    _who(request, "clinician")
    return await asyncio.to_thread(_m().deps.store.review_sessions, 60, bool(flagged))


@router.get("/api/review/sessions/{sid}")
async def review_session(sid: str, request: Request):
    who = _who(request, "clinician")
    data = await asyncio.to_thread(_m().deps.store.review_session, sid)
    if not data:
        raise HTTPException(404)
    store = _m().deps.store
    store.fire(store.audit, who["user"], "review_view_transcript", {"session": sid})
    return data


@router.post("/api/review/sessions/{sid}/verdict")
async def review_verdict(sid: str, request: Request):
    who = _who(request, "clinician")
    body = await request.json()
    verdict = str(body.get("verdict", ""))
    tier = body.get("expected_tier") or None
    if verdict not in ("safe", "unsafe", "wrong"):
        raise HTTPException(400, "verdict must be safe, unsafe or wrong")
    if tier is not None and tier not in TIERS:
        raise HTTPException(400, "unknown tier")
    try:
        uid = int(body.get("utterance_id"))
    except (TypeError, ValueError):
        raise HTTPException(400, "utterance_id required")
    correction = str(body.get("correction", ""))[:2000]
    if verdict != "safe" and not correction.strip() and not tier:
        raise HTTPException(400, "say what the answer should have been (text or tier)")
    store = _m().deps.store
    ok = await asyncio.to_thread(store.add_review, sid, uid, verdict, correction, tier, f"{who['name']} ({who['user']})"[:80])
    if not ok:
        raise HTTPException(404, "that answer was not found in this call")
    store.fire(store.audit, who["user"], "review_verdict", {"session": sid, "utterance": uid, "verdict": verdict})
    metrics.inc("review_verdict", verdict=verdict)
    return {"ok": True}


@router.get("/api/review/export")
async def review_export(request: Request):
    """Doctor corrections as JSON test cases: merge them into agent/seed/triage_scenarios.json after review."""
    _who(request, "clinician")
    return await asyncio.to_thread(_m().deps.store.export_corrections)


# ---------------------------------------------------------------- owner dashboard (admin)
@router.get("/api/owner/stats")
async def owner_stats(request: Request, days: int = 7):
    _who(request)
    days = max(1, min(int(days), 90))
    d = _m().deps
    data = await asyncio.to_thread(d.store.owner_stats, days)
    data["live"] = {"calls_active": len(d.hub.calls), "handovers_waiting": sum(1 for h in d.hub.handovers.values() if h["status"] == "waiting")}
    data["speed"] = metrics.summary()["latency"]
    data["counters"] = metrics.summary()["counters"]
    data["ai"] = {"llm_routes": d.llm.status(), "stt_routes": d.stt.status(), "voice_ok": await d.tts.healthy()}
    return data


# ---------------------------------------------------------------- demo helpers
@router.get("/api/demo/scenarios")
async def demo_scenarios():
    return SCENARIOS


@router.post("/api/admin/demo/reset")
async def demo_reset(request: Request):
    """Clear the hand-over queue shown in the staff console so a demo starts clean. Stored records and audit log are untouched."""
    who = _who(request)
    d = _m().deps
    n = len(d.hub.handovers)
    for hid in [k for k, h in d.hub.handovers.items() if h["status"] != "waiting" or h["created_at"] < time.time() - 60]:
        d.hub.handovers.pop(hid, None)
    await d.hub.broadcast_staff({"type": "snapshot", "handovers": [d.hub.public(h, with_transcript=False) for h in d.hub.handovers.values()]})
    d.store.fire(d.store.audit, who["user"], "demo_reset", {"cleared": n - len(d.hub.handovers)})
    return {"cleared": n - len(d.hub.handovers)}


__all__ = ["router", "claims_of"]
