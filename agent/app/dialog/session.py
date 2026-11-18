from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Line:
    text: str
    key: str | None = None  # key of a fixed script (pre-rendered audio)
    trusted: bool = True  # fixed scripts skip the output guard; dynamic text does not
    chunks: list[str] | None = None  # explicit speech chunks: small, reusable phrases that are cached individually


@dataclass
class HandoverRequest:
    reason: str  # emergency | distress | abuse | caller_requested | medical_advice_request | verification_failed | unclear | language | degraded | turn_limit
    urgency: str  # emergency | urgent | routine
    category: str = ""
    source: str = ""  # rules | llm | caller | system


@dataclass
class Reply:
    lines: list[Line]
    state: str
    handover: HandoverRequest | None = None
    end: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    intent: str | None = None
    safety: dict[str, str] = field(default_factory=dict)
    nlu_ms: int = 0
    event: dict[str, Any] | None = None  # side-effect event for persistence (e.g. appointment_booked)
    pending_analysis: Any = None  # asyncio.Task of the parallel AI safety check (reply already given; may interrupt)
    triage: dict[str, Any] | None = None  # urgency tier + structured brief for this reply (shown in the UI, stored, given to staff)


@dataclass
class Session:
    id: str
    started: float = field(default_factory=time.time)
    state: str = "IDLE"  # IDLE AWAIT_NAME AWAIT_DOB AWAIT_DEPT AWAIT_DATE AWAIT_TIME AWAIT_CONFIRM AWAIT_APPT_CONFIRM HANDOVER ENDED
    verified: bool = False
    patient: dict | None = None
    verify_attempts: int = 0
    claimed_name: str | None = None
    pending_intent: str | None = None
    unclear: int = 0
    turns: int = 0
    language: str = "en"
    flow: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    last_prompt: str = ""
    handover_id: str | None = None
    ended: bool = False
    client_ip: str = "unknown"
    doctor_turns: int = 0  # follow-up questions asked in the current doctor-style conversation
    disclaimer_given: bool = False
    triage: dict[str, Any] = field(default_factory=dict)  # intake facts (age) + the latest tier decision for this call
    role: str = "patient"  # who is testing: patient | owner | doctor (set by the start screen; used for analytics only)
