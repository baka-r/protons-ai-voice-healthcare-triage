"""Hub: live registry of calls, hand-overs and staff-console sockets."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

if TYPE_CHECKING:
    from app.call import CallSession

log = logging.getLogger("hub")


class Hub:
    def __init__(self) -> None:
        self.staff: set[WebSocket] = set()
        self.calls: dict[str, "CallSession"] = {}
        self.handovers: dict[str, dict[str, Any]] = {}

    async def broadcast_staff(self, event: dict) -> None:
        dead = []
        msg = json.dumps(event, ensure_ascii=False, default=str)
        for ws in list(self.staff):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.staff.discard(ws)

    def create_handover(self, session_id: str, reason: str, urgency: str, category: str, source: str, transcript: list[dict]) -> dict:
        hid = "HO-" + uuid.uuid4().hex[:6].upper()
        h = {
            "id": hid, "session_id": session_id, "reason": reason, "urgency": urgency, "category": category,
            "source": source, "status": "waiting", "created_at": time.time(), "transcript": list(transcript),
            "summary": None, "accepted_by": None,
        }
        self.handovers[hid] = h
        self._evict()
        return h

    def _evict(self, keep: int = 300) -> None:
        """Bound memory: drop the oldest finished hand-overs (waiting ones are never evicted)."""
        if len(self.handovers) <= keep:
            return
        finished = sorted((h for h in self.handovers.values() if h["status"] != "waiting"), key=lambda x: x["created_at"])
        for h in finished[: len(self.handovers) - keep]:
            self.handovers.pop(h["id"], None)

    def public(self, h: dict, with_transcript: bool = True) -> dict:
        out = {k: v for k, v in h.items() if k != "transcript"}
        if with_transcript:
            out["transcript"] = h["transcript"]
        return out
