"""PostgreSQL application records (the EMR stays the master record).

Mirrors the Sprint 1 ERD. Writes are fired off the call path (never block a reply).
The audit log is append-only and hash-chained so tampering is detectable.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any

from datetime import timedelta

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, delete, func, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session as DB, mapped_column

log = logging.getLogger("db")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex[:16]


class Base(DeclarativeBase):
    pass


class Role(Base):
    __tablename__ = "role"
    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)


class StaffUser(Base):
    __tablename__ = "staff_user"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.role_id"))
    display_name: Mapped[str] = mapped_column(String(80))


class Patient(Base):
    __tablename__ = "patient"
    patient_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    emr_patient_id: Mapped[str] = mapped_column(String(64), unique=True)


class Practitioner(Base):
    __tablename__ = "practitioner"
    practitioner_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(80))


class CallSession(Base):
    __tablename__ = "call_session"
    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patient.patient_id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="en")
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    turns: Mapped[int] = mapped_column(Integer, default=0)


class Consent(Base):
    __tablename__ = "consent"
    consent_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("call_session.session_id"))
    kind: Mapped[str] = mapped_column(String(40))  # recording_notice
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Utterance(Base):
    __tablename__ = "utterance"
    utterance_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("call_session.session_id"))
    speaker: Mapped[str] = mapped_column(String(12))  # caller | assistant
    text: Mapped[str] = mapped_column(Text)  # PII-masked
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    timings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TriageAssessment(Base):
    """Result of the safety screen - NOT a diagnosis."""
    __tablename__ = "triage_assessment"
    assessment_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("call_session.session_id"))
    red_flag: Mapped[bool] = mapped_column(Boolean)
    category: Mapped[str] = mapped_column(String(40), default="")
    source: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Escalation(Base):
    __tablename__ = "escalation"
    escalation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("call_session.session_id"))
    assessment_id: Mapped[str | None] = mapped_column(ForeignKey("triage_assessment.assessment_id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(40))
    urgency: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Appointment(Base):
    __tablename__ = "appointment"
    appointment_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.patient_id"))
    practitioner_id: Mapped[str | None] = mapped_column(ForeignKey("practitioner.practitioner_id"), nullable=True)
    emr_appointment_id: Mapped[str] = mapped_column(String(64))
    department: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="booked")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40))


class DocumentVersion(Base):
    __tablename__ = "document_version"
    version_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_document.document_id"))
    version: Mapped[int] = mapped_column(Integer)
    approval_status: Mapped[str] = mapped_column(String(20))
    approved_by: Mapped[str] = mapped_column(String(200), default="")
    expires: Mapped[str | None] = mapped_column(String(16), nullable=True)
    included: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)


class DocumentChunk(Base):
    __tablename__ = "document_chunk"
    chunk_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_version.version_id"))
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding_id: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ResponseSource(Base):
    __tablename__ = "response_source"
    utterance_id: Mapped[int] = mapped_column(ForeignKey("utterance.utterance_id"), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunk.chunk_id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)


class AuditLog(Base):
    __tablename__ = "audit_log"
    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("staff_user.user_id"), nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class EvalCase(Base):
    """Synthetic evaluation case (NOT training data). clinical_review stays PENDING until a clinician signs off."""
    __tablename__ = "eval_case"
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(48))
    lang: Mapped[str] = mapped_column(String(12))
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), default="IDLE")
    expect: Mapped[str] = mapped_column(String(48))
    expect_rules: Mapped[str] = mapped_column(String(48), default="")
    needs_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    forbid: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[str] = mapped_column(String(24), default="synthetic")
    clinical_review: Mapped[str] = mapped_column(String(16), default="PENDING")


class EvalRun(Base):
    __tablename__ = "eval_run"
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    mode: Mapped[str] = mapped_column(String(16))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class StaffAccount(Base):
    """A named person who can sign in to the staff site (role: support | clinician | admin). Passwords are scrypt-hashed."""
    __tablename__ = "staff_account"
    username: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(16))
    pw_hash: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionInfo(Base):
    """Who is testing (patient / owner / doctor) and the consent they gave on the start screen."""
    __tablename__ = "session_info"
    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    role: Mapped[str] = mapped_column(String(12), default="patient")
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TriageResult(Base):
    """The urgency tier suggested for a call (NOT a diagnosis) with the de-identified brief that was given to staff."""
    __tablename__ = "triage_result"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    topic: Mapped[str] = mapped_column(String(80), default="")
    tier: Mapped[str] = mapped_column(String(20))
    age_group: Mapped[str] = mapped_column(String(16), default="unknown")
    source: Mapped[str] = mapped_column(String(16), default="")  # interview | doctor_mode | rules | llm
    brief: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Feedback(Base):
    """Thumbs up/down (+ optional comment) from whoever is testing, tied to the answer they were reacting to."""
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    rating: Mapped[str] = mapped_column(String(8))  # up | down
    comment: Mapped[str] = mapped_column(Text, default="")
    caller_text: Mapped[str] = mapped_column(Text, default="")
    assistant_text: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(12), default="patient")
    lang: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Review(Base):
    """A clinician's verdict on one thing Hania said. unsafe / wrong rows (with the correction) become new test cases."""
    __tablename__ = "review"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    utterance_id: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(12))  # safe | unsafe | wrong
    correction: Mapped[str] = mapped_column(Text, default="")
    expected_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    caller_text: Mapped[str] = mapped_column(Text, default="")
    assistant_text: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def chain_hash(prev: str, ts: str, actor: str, action: str, payload: dict) -> str:
    body = json.dumps({"p": prev, "t": ts, "a": actor, "x": action, "d": payload}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


class Store:
    def __init__(self, url: str):
        self.engine = create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)
        self._audit_lock = threading.Lock()
        self.ok = False
        self._tasks: set[asyncio.Task] = set()

    # -------------------------------------------------------------- lifecycle
    def init(self, retries: int = 30) -> None:
        for i in range(retries):
            try:
                Base.metadata.create_all(self.engine)
                with DB(self.engine) as db:
                    if not db.scalar(select(Role).limit(1)):
                        db.add_all([Role(role_id=1, name="support_staff"), Role(role_id=2, name="clinician"), Role(role_id=3, name="admin")])
                        db.flush()
                        db.add(StaffUser(user_id="staff-demo", role_id=1, display_name="Demo Support Agent"))
                    db.commit()
                self.ok = True
                return
            except Exception as e:  # database still starting
                log.info("db not ready (%s), retry %d", type(e).__name__, i + 1)
                time.sleep(2)
        log.error("database unavailable - running without persistence")

    def fire(self, fn, *args, **kw) -> None:
        """Run a write in a worker thread without awaiting it (keeps replies fast)."""
        if not self.ok:
            return

        async def run():
            try:
                await asyncio.to_thread(fn, *args, **kw)
            except Exception:
                log.exception("db write failed: %s", getattr(fn, "__name__", fn))

        t = asyncio.get_running_loop().create_task(run())
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # -------------------------------------------------------------- audit
    def audit(self, actor: str, action: str, payload: dict[str, Any] | None = None, actor_user_id: str | None = None) -> None:
        payload = payload or {}
        with self._audit_lock, DB(self.engine) as db:
            last = db.scalar(select(AuditLog).order_by(AuditLog.audit_id.desc()).limit(1))
            prev = last.hash if last else "0" * 64
            ts = _now()
            h = chain_hash(prev, ts.isoformat(), actor, action, payload)
            db.add(AuditLog(ts=ts, actor=actor, action=action, payload=payload, prev_hash=prev, hash=h, actor_user_id=actor_user_id))
            db.commit()

    def verify_audit(self) -> dict:
        with DB(self.engine) as db:
            prev, n = "0" * 64, 0
            for row in db.scalars(select(AuditLog).order_by(AuditLog.audit_id)):
                n += 1
                if row.prev_hash != prev or chain_hash(prev, row.ts.isoformat(), row.actor, row.action, row.payload) != row.hash:
                    return {"ok": False, "broken_at": row.audit_id, "checked": n}
                prev = row.hash
            return {"ok": True, "checked": n}

    # -------------------------------------------------------------- records
    def create_session(self, session_id: str) -> None:
        with DB(self.engine) as db:
            db.add(CallSession(session_id=session_id))
            db.add(Consent(session_id=session_id, kind="recording_notice", granted=True))
            db.commit()

    def end_session(self, session_id: str, outcome: str, turns: int, language: str, emr_patient_id: str | None) -> None:
        with DB(self.engine) as db:
            cs = db.get(CallSession, session_id)
            if not cs:
                return
            cs.ended_at, cs.outcome, cs.turns, cs.language = _now(), outcome, turns, language
            if emr_patient_id:
                cs.patient_id = self._patient_id(db, emr_patient_id)
            db.commit()

    def _patient_id(self, db: DB, emr_patient_id: str) -> str:
        p = db.scalar(select(Patient).where(Patient.emr_patient_id == emr_patient_id))
        if not p:
            p = Patient(emr_patient_id=emr_patient_id)
            db.add(p)
            db.flush()
        return p.patient_id

    def add_utterance(self, session_id: str, speaker: str, text: str, intent: str | None = None, timings: dict | None = None) -> int:
        with DB(self.engine) as db:
            u = Utterance(session_id=session_id, speaker=speaker, text=text, intent=intent, timings=timings)
            db.add(u)
            db.commit()
            return u.utterance_id

    def add_utterance_with_sources(self, session_id: str, text: str, intent: str | None, sources: list[dict]) -> None:
        """Assistant utterance + the approved document chunks it was spoken from (RESPONSE_SOURCE)."""
        uid = self.add_utterance(session_id, "assistant", text, intent, None)
        for s in sources:
            self.add_response_source(uid, s["chunk_id"], float(s.get("score", 0.0)))

    def add_assessment(self, session_id: str, red_flag: bool, category: str, source: str) -> str:
        with DB(self.engine) as db:
            a = TriageAssessment(session_id=session_id, red_flag=red_flag, category=category, source=source)
            db.add(a)
            db.commit()
            return a.assessment_id

    def create_escalation(self, esc_id: str, session_id: str, reason: str, urgency: str, category: str, source: str) -> None:
        with DB(self.engine) as db:
            a = TriageAssessment(session_id=session_id, red_flag=urgency == "emergency", category=category, source=source)
            db.add(a)
            db.flush()
            db.add(Escalation(escalation_id=esc_id, session_id=session_id, assessment_id=a.assessment_id, reason=reason, urgency=urgency))
            db.commit()

    def update_escalation(self, esc_id: str, **fields: Any) -> None:
        with DB(self.engine) as db:
            e = db.get(Escalation, esc_id)
            if e:
                for k, v in fields.items():
                    setattr(e, k, v)
                db.commit()

    def add_appointment(self, emr_patient_id: str, appt: dict) -> None:
        with DB(self.engine) as db:
            pid = self._patient_id(db, emr_patient_id)
            db.add(Appointment(patient_id=pid, emr_appointment_id=appt["id"], department=appt["department"], starts_at=f"{appt['date']}T{appt['time']}"))
            db.commit()

    def set_appointment_status(self, emr_appointment_id: str, status: str) -> None:
        with DB(self.engine) as db:
            for a in db.scalars(select(Appointment).where(Appointment.emr_appointment_id == emr_appointment_id)):
                a.status = status
            db.commit()

    def add_response_source(self, utterance_id: int, chunk_id: str, score: float) -> None:
        with DB(self.engine) as db:
            if db.get(DocumentChunk, chunk_id):
                db.add(ResponseSource(utterance_id=utterance_id, chunk_id=chunk_id, score=score))
                db.commit()

    def record_knowledge(self, docs: list) -> None:
        """Persist every document version (included or not) so exclusions are auditable."""
        with DB(self.engine) as db:
            for d in docs:
                if not db.get(KnowledgeDocument, d.doc_id):
                    db.add(KnowledgeDocument(document_id=d.doc_id, title=d.title, category=d.category))
                vid = f"{d.doc_id}:v{d.version}"
                existing = db.get(DocumentVersion, vid)
                if existing:
                    existing.approval_status, existing.included, existing.exclusion_reason = d.approval_status, d.included, d.exclusion_reason
                else:
                    db.add(DocumentVersion(version_id=vid, document_id=d.doc_id, version=d.version, approval_status=d.approval_status,
                                           approved_by=(d.approved_by or "")[:80], expires=d.expires, included=d.included, exclusion_reason=d.exclusion_reason))
                    db.flush()
                    for i, (heading, text) in enumerate(d.chunks):
                        db.add(DocumentChunk(chunk_id=f"{vid}:{i}", version_id=vid, idx=i, text=text, embedding_id=f"{vid}:{i}" if d.included else None))
            db.commit()

    def upsert_eval_cases(self, cases: list[dict]) -> int:
        with DB(self.engine) as db:
            for c in cases:
                row = db.get(EvalCase, c["id"]) or EvalCase(case_id=c["id"])
                row.category, row.lang, row.text, row.state = c["category"], c["lang"], c["text"], c.get("state", "IDLE")
                row.expect, row.expect_rules, row.needs_llm = c["expect"], c.get("expect_rules", ""), bool(c.get("needs_llm"))
                row.forbid, row.notes = list(c.get("forbid", [])), c.get("notes", "")
                row.provenance, row.clinical_review = "synthetic", "PENDING"
                db.merge(row)
            db.commit()
            return len(cases)

    def record_eval_run(self, mode: str, metrics: dict) -> str:
        with DB(self.engine) as db:
            r = EvalRun(mode=mode, metrics=metrics)
            db.add(r)
            db.commit()
            return r.run_id

    def seed_reference_data(self, patients: list[dict], departments: list[str]) -> dict:
        """Idempotent: synthetic patients (EMR links) and practitioners (3 per department)."""
        import random

        rnd = random.Random(11)
        first = ["Dr. Amina", "Dr. Bashir", "Dr. Chand", "Dr. Dilnawaz", "Dr. Erum", "Dr. Farhan", "Dr. Ghazala", "Dr. Haroon"]
        last = ["Qasim", "Rehman", "Tariq", "Yousuf", "Zahid", "Nadeem", "Saleem"]
        with DB(self.engine) as db:
            for p in patients:
                if not db.scalar(select(Patient).where(Patient.emr_patient_id == p["id"])):
                    db.add(Patient(emr_patient_id=p["id"]))
            existing = {r.department for r in db.scalars(select(Practitioner))}
            n = 0
            for d in departments:
                if d in existing:
                    continue
                for _ in range(3):
                    db.add(Practitioner(name=f"{rnd.choice(first)} {rnd.choice(last)}", department=d))
                    n += 1
            db.commit()
        return {"patients": len(patients), "new_practitioners": n}

    def list_escalations(self, limit: int = 50) -> list[dict]:
        with DB(self.engine) as db:
            rows = db.scalars(select(Escalation).order_by(Escalation.created_at.desc()).limit(limit)).all()
            return [{"id": r.escalation_id, "session_id": r.session_id, "reason": r.reason, "urgency": r.urgency, "status": r.status,
                     "created_at": r.created_at.isoformat()} for r in rows]

    # -------------------------------------------------------------- staff accounts
    def bootstrap_accounts(self, owner_password: str) -> None:
        """First start only: create the owner (admin) account so someone can sign in and create the doctors."""
        from app.security import hash_password

        with DB(self.engine) as db:
            if db.scalar(select(StaffAccount).limit(1)):
                return
            db.add(StaffAccount(username="owner", display_name="Owner", role="admin", pw_hash=hash_password(owner_password)))
            db.commit()

    def login_account(self, username: str, password: str) -> dict | None:
        from app.security import check_password

        with DB(self.engine) as db:
            a = db.get(StaffAccount, username.strip().lower()[:40])
            ok = bool(a and a.active and check_password(password, a.pw_hash))
            if not ok:
                check_password(password, "scrypt$00$00")  # keep timing similar for unknown users
                return None
            a.last_login = _now()
            db.commit()
            return {"username": a.username, "name": a.display_name, "role": a.role}

    def list_accounts(self) -> list[dict]:
        with DB(self.engine) as db:
            return [{"username": a.username, "name": a.display_name, "role": a.role, "active": a.active,
                     "last_login": a.last_login.isoformat() if a.last_login else None} for a in db.scalars(select(StaffAccount).order_by(StaffAccount.created_at))]

    def create_account(self, username: str, name: str, role: str, password: str) -> bool:
        from app.security import hash_password

        username = username.strip().lower()[:40]
        with DB(self.engine) as db:
            if db.get(StaffAccount, username):
                return False
            db.add(StaffAccount(username=username, display_name=name.strip()[:80] or username, role=role, pw_hash=hash_password(password)))
            db.commit()
            return True

    def set_account(self, username: str, active: bool | None = None, password: str | None = None) -> bool:
        from app.security import hash_password

        with DB(self.engine) as db:
            a = db.get(StaffAccount, username.strip().lower())
            if not a:
                return False
            if active is not None:
                a.active = active
            if password:
                a.pw_hash = hash_password(password)
            db.commit()
            return True

    # -------------------------------------------------------------- consent, triage, feedback
    def add_session_info(self, session_id: str, role: str, consent: bool) -> None:
        with DB(self.engine) as db:
            db.merge(SessionInfo(session_id=session_id, role=role if role in ("patient", "owner", "doctor", "qa") else "patient", consent=consent))
            db.commit()

    def add_triage(self, session_id: str, brief: dict) -> None:
        with DB(self.engine) as db:
            db.add(TriageResult(session_id=session_id, topic=str(brief.get("topic", ""))[:80], tier=str(brief.get("tier") or "see_doctor_soon"),
                                age_group=str(brief.get("age_group", "unknown")), source=str(brief.get("source", ""))[:16], brief=brief))
            db.commit()

    def add_feedback(self, session_id: str, rating: str, comment: str, caller_text: str, assistant_text: str, role: str, lang: str) -> None:
        with DB(self.engine) as db:
            db.add(Feedback(session_id=session_id, rating=rating, comment=comment[:1000], caller_text=caller_text[:600],
                            assistant_text=assistant_text[:900], role=role, lang=lang[:8]))
            db.commit()

    # -------------------------------------------------------------- doctor review
    def review_sessions(self, limit: int = 60, only_flagged: bool = False) -> list[dict]:
        with DB(self.engine) as db:
            rows = db.scalars(select(CallSession).order_by(CallSession.started_at.desc()).limit(limit * 3 if only_flagged else limit)).all()
            out = []
            for r in rows:
                sid = r.session_id
                said = db.scalar(select(func.count()).select_from(Utterance).where(Utterance.session_id == sid)) or 0
                if not said:
                    continue  # purged by retention, or nothing happened
                tri = db.scalar(select(TriageResult).where(TriageResult.session_id == sid).order_by(TriageResult.id.desc()).limit(1))
                down = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.session_id == sid, Feedback.rating == "down")) or 0
                up = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.session_id == sid, Feedback.rating == "up")) or 0
                reviewed = db.scalar(select(func.count()).select_from(Review).where(Review.session_id == sid)) or 0
                info = db.get(SessionInfo, sid)
                if only_flagged and not (down or (tri and tri.tier in ("same_day", "emergency")) or r.outcome == "handover"):
                    continue
                out.append({"session_id": sid, "started_at": r.started_at.isoformat(), "language": r.language, "outcome": r.outcome,
                            "turns": r.turns, "tier": tri.tier if tri else None, "topic": tri.topic if tri else "", "thumbs_up": up,
                            "thumbs_down": down, "reviewed": reviewed, "role": info.role if info else "patient"})
                if len(out) >= limit:
                    break
            return out

    def review_session(self, session_id: str) -> dict | None:
        with DB(self.engine) as db:
            cs = db.get(CallSession, session_id)
            if not cs:
                return None
            uts = db.scalars(select(Utterance).where(Utterance.session_id == session_id).order_by(Utterance.utterance_id)).all()
            reviews = db.scalars(select(Review).where(Review.session_id == session_id).order_by(Review.id)).all()
            fb = db.scalars(select(Feedback).where(Feedback.session_id == session_id).order_by(Feedback.id)).all()
            tri = db.scalars(select(TriageResult).where(TriageResult.session_id == session_id).order_by(TriageResult.id)).all()
            return {
                "session_id": session_id, "started_at": cs.started_at.isoformat(), "language": cs.language, "outcome": cs.outcome,
                "utterances": [{"id": u.utterance_id, "speaker": u.speaker, "text": u.text, "intent": u.intent, "at": u.created_at.isoformat()} for u in uts],
                "reviews": [{"id": v.id, "utterance_id": v.utterance_id, "verdict": v.verdict, "correction": v.correction, "expected_tier": v.expected_tier,
                             "reviewer": v.reviewer, "at": v.created_at.isoformat()} for v in reviews],
                "feedback": [{"rating": f.rating, "comment": f.comment, "assistant_text": f.assistant_text, "role": f.role} for f in fb],
                "triage": [{"tier": t.tier, "topic": t.topic, "age_group": t.age_group, "source": t.source, "brief": t.brief} for t in tri],
            }

    def add_review(self, session_id: str, utterance_id: int, verdict: str, correction: str, expected_tier: str | None, reviewer: str) -> bool:
        with DB(self.engine) as db:
            u = db.get(Utterance, utterance_id)
            if not u or u.session_id != session_id or u.speaker != "assistant":
                return False
            prev = db.scalar(select(Utterance).where(Utterance.session_id == session_id, Utterance.speaker == "caller",
                                                    Utterance.utterance_id < utterance_id).order_by(Utterance.utterance_id.desc()).limit(1))
            existing = db.scalar(select(Review).where(Review.utterance_id == utterance_id, Review.reviewer == reviewer))
            row = existing or Review(session_id=session_id, utterance_id=utterance_id, reviewer=reviewer)
            row.verdict, row.correction, row.expected_tier = verdict, correction[:2000], expected_tier
            row.caller_text, row.assistant_text = (prev.text if prev else "")[:600], u.text[:900]
            db.add(row)
            db.commit()
            return True

    def export_corrections(self) -> list[dict]:
        """Clinician verdicts as test cases: what the caller said, what Hania answered, what the doctor wants instead."""
        with DB(self.engine) as db:
            rows = db.scalars(select(Review).where(Review.verdict.in_(("unsafe", "wrong"))).order_by(Review.id)).all()
            return [{"id": f"review-{r.id}", "caller_text": r.caller_text, "hania_said": r.assistant_text, "verdict": r.verdict,
                     "doctor_correction": r.correction, "expected_tier": r.expected_tier, "reviewer": r.reviewer,
                     "provenance": "clinician_review", "clinical_review": "SIGNED_BY_REVIEWER"} for r in rows]

    # -------------------------------------------------------------- owner dashboard
    def owner_stats(self, days: int = 7) -> dict:
        since = _now() - timedelta(days=days)
        with DB(self.engine) as db:
            def grouped(col, *where):
                q = select(col, func.count())
                if where:
                    q = q.where(*where)
                return {str(k or "none"): n for k, n in db.execute(q.group_by(col)).all()}

            calls = db.scalar(select(func.count()).select_from(CallSession).where(CallSession.started_at >= since)) or 0
            avg_turns = db.scalar(select(func.avg(CallSession.turns)).where(CallSession.started_at >= since)) or 0
            rec = db.scalars(select(Feedback).where(Feedback.created_at >= since, Feedback.comment != "").order_by(Feedback.id.desc()).limit(12)).all()
            intents = db.execute(select(Utterance.intent, func.count()).where(
                Utterance.created_at >= since, Utterance.speaker == "assistant", Utterance.intent.is_not(None)
            ).group_by(Utterance.intent).order_by(func.count().desc()).limit(8)).all()
            return {
                "days": days, "calls": calls, "avg_turns": round(float(avg_turns), 1),
                "outcomes": grouped(CallSession.outcome, CallSession.started_at >= since),
                "languages": grouped(CallSession.language, CallSession.started_at >= since),
                "handovers_by_urgency": grouped(Escalation.urgency, Escalation.created_at >= since),
                "handover_status": grouped(Escalation.status, Escalation.created_at >= since),
                "handover_reasons": grouped(Escalation.reason, Escalation.created_at >= since),
                "tiers": grouped(TriageResult.tier, TriageResult.created_at >= since),
                "tier_topics": grouped(TriageResult.topic, TriageResult.created_at >= since, TriageResult.topic != ""),
                "testers": grouped(SessionInfo.role, SessionInfo.created_at >= since),
                "feedback": grouped(Feedback.rating, Feedback.created_at >= since),
                "recent_comments": [{"rating": f.rating, "comment": f.comment, "answer": f.assistant_text[:200], "role": f.role,
                                     "at": f.created_at.isoformat()} for f in rec],
                "reviews": grouped(Review.verdict, Review.created_at >= since),
                "appointments": grouped(Appointment.status),
                "top_intents": {str(k): n for k, n in intents},
            }

    # -------------------------------------------------------------- retention
    def purge_old(self, days: int) -> dict:
        """Delete masked transcripts and feedback text older than `days`. Verdicts, tiers and counts are kept."""
        cutoff = _now() - timedelta(days=days)
        with DB(self.engine) as db:
            old = select(Utterance.utterance_id).where(Utterance.created_at < cutoff)
            rs = db.execute(delete(ResponseSource).where(ResponseSource.utterance_id.in_(old))).rowcount
            us = db.execute(delete(Utterance).where(Utterance.created_at < cutoff)).rowcount
            fb = db.execute(update(Feedback).where(Feedback.created_at < cutoff).values(caller_text="", assistant_text="", comment="")).rowcount
            rv = db.execute(update(Review).where(Review.created_at < cutoff).values(caller_text="", assistant_text="")).rowcount
            db.commit()
        return {"utterances": us, "sources": rs, "feedback_text": fb, "review_text": rv}
