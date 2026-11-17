"""Engine flows with fake LLM / EMR / RAG (no network)."""
from datetime import timedelta

import pytest

from app.config import Settings
from app.dialog import rules
from app.dialog.engine import Engine
from app.dialog.session import Session
from app.services.llm import Analysis

DEPTS = [
    {"id": "cardio", "name": "Cardiology", "aliases": ["heart", "cardiologist"]},
    {"id": "gm", "name": "General Medicine", "aliases": ["general physician", "gp"]},
    {"id": "ent", "name": "ENT", "aliases": ["ear nose throat"]},
]


class FakeLLM:
    def __init__(self, analysis=None):
        self.analysis, self.calls = analysis, 0

    async def analyze(self, **kw):
        self.calls += 1
        return self.analysis


class FakeEMR:
    def __init__(self):
        self.booked, self.cancelled = [], []
        tomorrow = (rules.now_local().date() + timedelta(days=1)).isoformat()
        self.tomorrow = tomorrow

    async def departments(self):
        return DEPTS

    async def find_patient(self, name, dob):
        if dob == "1990-03-12" and "ayesha" in name.lower():
            return {"id": "P-1001", "name": "Ayesha Khan", "birthDate": dob}
        return None

    async def slots(self, dept, date):
        if date == self.tomorrow:
            return [{"id": f"{dept}|{date}|{t}", "date": date, "time": t, "department_id": dept} for t in ("09:00", "10:30", "14:00")]
        return []

    async def next_available(self, dept, after):
        return self.tomorrow

    async def appointments(self, pid):
        return [{"id": "A-1", "department": "Cardiology", "department_id": "cardio", "date": self.tomorrow, "time": "10:00", "status": "booked"}]

    async def book(self, pid, slot_id):
        d, date, t = slot_id.split("|")
        a = {"id": "A-99", "department": "Cardiology", "department_id": d, "date": date, "time": t, "status": "booked"}
        self.booked.append(a)
        return a

    async def cancel(self, aid):
        self.cancelled.append(aid)
        return True


class FakeRAG:
    def __init__(self, hits):
        self.hits = hits

    async def search(self, q, k=3, category=None):
        return self.hits


def mk(analysis=None, hits=None):
    llm, emr = FakeLLM(analysis), FakeEMR()
    return Engine(Settings(), llm, emr, FakeRAG(hits or [])), llm, emr


def A(**kw):
    base = dict(language="en", intent="other", red_flag=False, distress=False, red_flag_reason="", department=None, date=None, time=None, info_query=None, confidence=0.9)
    base.update(kw)
    return Analysis(**base)


async def say(eng, s, text):
    r = await eng.handle(s, text)
    return r, " ".join(x.text for x in r.lines)


async def test_red_flag_rules_beat_everything_and_skip_llm():
    eng, llm, _ = mk(A(intent="book_appointment"))
    s = Session(id="t")
    r, _ = await say(eng, s, "I have chest pain but also want an appointment")
    assert r.handover and r.handover.urgency == "emergency" and r.handover.source == "rules"
    assert llm.calls == 0


async def test_llm_can_add_caution_but_not_remove_it():
    eng, _, _ = mk(A(intent="other", red_flag=True, red_flag_reason="possible stroke"))
    r, _ = await say(eng, Session(id="t"), "my uncle seems a bit odd today")
    assert r.handover and r.handover.source == "llm" and r.handover.urgency == "emergency"
    # LLM says harmless, rules say red flag -> rules win
    eng2, _, _ = mk(A(intent="greeting"))
    r2, _ = await say(eng2, Session(id="t"), "I can't breathe")
    assert r2.handover and r2.handover.source == "rules"


async def test_self_harm_uses_distress_script():
    eng, _, _ = mk()
    r, text = await say(eng, Session(id="t"), "I want to kill myself")
    assert r.handover.reason == "distress" and "not have to face it alone" in text.replace("don't", "not") or "alone" in text


async def test_medical_advice_is_refused_and_handed_over():
    eng, _, _ = mk(A(intent="medical_question"))
    for q in ("what medicine should I take for fever", "can I take ibuprofen for my rash"):
        r, text = await say(eng, Session(id="t"), q)
        assert r.handover and r.handover.reason == "medical_advice_request"
        assert "mg" not in text and "tablet" not in text


async def test_human_request():
    eng, _, _ = mk(A(intent="talk_to_human"))
    r, _ = await say(eng, Session(id="t"), "can I speak to a real person")
    assert r.handover and r.handover.reason == "caller_requested"


async def test_full_booking_flow():
    eng, llm, emr = mk(A(intent="book_appointment"))
    s = Session(id="t")
    r, _ = await say(eng, s, "I'd like to book an appointment")
    assert s.state == "AWAIT_NAME"
    r, text = await say(eng, s, "my name is Ayesha Khan and my date of birth is 12 March 1990")
    assert s.verified and s.state == "AWAIT_DEPT", text
    llm.analysis = A(intent="provide_info", department="Cardiology")
    r, text = await say(eng, s, "cardiology please")
    assert s.state == "AWAIT_DATE"
    llm.analysis = A(intent="provide_info", date=emr.tomorrow)
    r, text = await say(eng, s, "tomorrow")
    assert s.state == "AWAIT_TIME" and "9:00 AM" in text
    llm.analysis = A(intent="provide_info", time="10:30")
    r, text = await say(eng, s, "10:30 please")
    assert s.state == "AWAIT_CONFIRM"
    r, text = await say(eng, s, "yes")
    assert emr.booked and s.state == "IDLE" and r.event["type"] == "appointment_booked"


async def test_verification_fails_three_times_then_handover():
    eng, _, _ = mk(A(intent="cancel_appointment"))
    s = Session(id="t")
    await say(eng, s, "cancel my appointment")
    r = None
    for _ in range(3):
        r, _ = await say(eng, s, "my name is Bob Smith and my date of birth is 1 January 1980")
    assert r.handover and r.handover.reason == "verification_failed"


async def test_name_and_dob_never_sent_to_llm():
    eng, llm, _ = mk(A(intent="book_appointment"))
    s = Session(id="t")
    await say(eng, s, "book an appointment")
    calls = llm.calls
    await say(eng, s, "my name is Ayesha Khan and my date of birth is 12 March 1990")
    assert llm.calls == calls


async def test_info_uses_approved_chunk_verbatim():
    hit = {"chunk_id": "x", "text": "Our outpatient clinics are open Monday to Saturday from 9 AM to 5 PM.", "title": "Hours", "version": 2, "score": 0.8}
    eng, _, _ = mk(A(intent="hospital_info", info_query="opd timings"), hits=[hit])
    r, text = await say(eng, Session(id="t"), "what are your OPD timings")
    assert hit["text"] in text and r.sources and not r.handover


async def test_info_with_no_match_does_not_guess():
    eng, _, _ = mk(A(intent="hospital_info"), hits=[])
    r, text = await say(eng, Session(id="t"), "what are your opd timings")
    assert "don't have that information" in text and not r.handover


async def test_guard_blocks_unsafe_retrieved_text():
    hit = {"chunk_id": "x", "text": "Take 500 mg of paracetamol.", "title": "Bad", "version": 1, "score": 0.9}
    eng, _, _ = mk(A(intent="hospital_info"), hits=[hit])
    r, _ = await say(eng, Session(id="t"), "what are your opd timings")
    assert r.handover and r.handover.reason == "degraded"


async def test_llm_down_fails_closed_for_free_text():
    # AI safety net offline: unrecognised free text is handed to a human immediately (it could be an emergency in unusual words)
    eng, _, _ = mk(None)
    r1, _ = await say(eng, Session(id="t"), "blah blah something unusual")
    assert r1.handover and r1.handover.reason == "degraded"
    # ...but a bare noise word is simply re-asked once, then handed over
    s = Session(id="t2")
    n1, _ = await say(eng, s, "hmm")
    assert not n1.handover
    n2, _ = await say(eng, s, "uh")
    assert n2.handover


async def test_symptoms_with_llm_offline_go_to_a_human():
    eng, _, _ = mk(None)
    r, _ = await say(eng, Session(id="t"), "I'd like an appointment, I have a headache")
    assert r.handover and r.handover.category == "symptoms_while_ai_offline"




async def test_turn_limit():
    eng, _, _ = mk(A(intent="greeting"))
    s = Session(id="t", turns=eng.s.max_turns)
    r, _ = await say(eng, s, "hello")
    assert r.handover and r.handover.reason == "turn_limit"


def test_rule_helpers():
    assert rules.is_yes(rules.normalize("Yes, please") if hasattr(rules, "normalize") else "yes please")
    assert rules.pick_slot("the second one", ["09:00", "10:30", "14:00"], None) == "10:30"
    assert rules.pick_slot("afternoon", ["09:00", "10:30", "14:00"], None) == "14:00"
    assert rules.pick_slot("10:30", ["09:00", "10:30", "14:00"], None) == "10:30"
    assert rules.extract_name("my name is ayesha khan") == "Ayesha Khan"
    assert rules.extract_name("i want to book an appointment") is None
    assert str(rules.parse_dob("12 March 1990")) == "1990-03-12"
    assert rules.match_department("i need the heart doctor", DEPTS)["id"] == "cardio"
    assert rules.match_department("ent please", DEPTS)["id"] == "ent"


async def test_urdu_hindi_callers_are_served_not_handed_over():
    eng, _, _ = mk(A(language="ur", intent="book_appointment", confidence=0.9))
    s = Session(id="t")
    r, _ = await say(eng, s, "مجھے ڈاکٹر سے ملنا ہے")
    assert r.handover is None and s.state == "AWAIT_NAME"
