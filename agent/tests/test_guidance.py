"""Approved general guidance for ordinary symptoms - and the hard limits around it."""
import pytest

from app.config import Settings
from app.dialog.engine import Engine
from app.dialog.session import Session
from tests.test_engine import FakeEMR, FakeLLM, A

TEXT = ("I can't tell what is causing it, but in general it helps to rest and take small sips of water, or an oral rehydration drink, "
        "little and often. Get urgent help if there is blood in the vomit or severe stomach pain.")
HIT = {"chunk_id": "symptom-guidance:v1:0", "text": TEXT, "title": "General Health Guidance", "version": 1, "score": 0.85, "cosine": 0.80}


class GuidanceRAG:
    def __init__(self, hit=HIT):
        self.hit, self.calls = hit, []

    async def search(self, q, k=3, category=None):
        self.calls.append(category)
        return [self.hit] if (category == "symptom_guidance" and self.hit) else []


def mk(analysis, rag=None, **settings):
    return Engine(Settings(**settings), FakeLLM(analysis), FakeEMR(), rag or GuidanceRAG())


def say_(r):
    return " ".join(x.text for x in r.lines)


async def test_ordinary_symptom_gets_guidance_not_a_handover():
    eng = mk(A(intent="medical_question"))
    r = await eng.handle(Session(id="t"), "I have a minor burn on my arm, what should I do")
    assert r.handover is None and r.intent == "symptom_guidance"
    t = say_(r)
    assert "can't diagnose or recommend medicines" in t and TEXT in t and "connect you to our staff" in t
    assert r.sources and r.event["type"] == "symptom_guidance"
    assert not any(w in t.lower() for w in (" mg", "tablet", "paracetamol", "ibuprofen"))


@pytest.mark.parametrize("text", [
    "what medicine should I take for vomiting", "can I take something for this headache", "which tablet is best for a fever",
    "my baby is vomiting what should I do", "my daughter has a fever what to do", "I'm pregnant and feeling sick what should I do",
    "my grandmother is dizzy what should I do", "what dose of paracetamol for a cough", "can you diagnose my vomiting",
])
async def test_medicines_children_pregnancy_diagnosis_always_go_to_a_person(text):
    eng = mk(A(intent="medical_question"))
    r = await eng.handle(Session(id="t"), text)
    assert r.handover and r.handover.reason == "medical_advice_request", text


async def test_red_flags_still_beat_guidance():
    r = await mk(A(intent="medical_question")).handle(Session(id="t"), "I'm vomiting blood, what should I do")
    assert r.handover and r.handover.urgency == "emergency"
    r = await mk(A(intent="medical_question", red_flag=True, red_flag_reason="severe")).handle(Session(id="t"), "I feel sick and awful, what to do")
    assert r.handover and r.handover.urgency == "emergency"


async def test_weak_match_or_missing_guidance_hands_over():
    weak = dict(HIT, cosine=0.45)
    r = await mk(A(intent="medical_question"), GuidanceRAG(weak)).handle(Session(id="t"), "I feel odd, what to do")
    assert r.handover and r.handover.reason == "medical_advice_request"
    r = await mk(A(intent="medical_question"), GuidanceRAG(None)).handle(Session(id="t"), "I feel odd, what to do")
    assert r.handover


async def test_feature_can_be_switched_off():
    r = await mk(A(intent="medical_question"), symptom_guidance=False).handle(Session(id="t"), "I feel sick, what should I do")
    assert r.handover and r.handover.reason == "medical_advice_request"


async def test_unsafe_guidance_text_is_never_spoken():
    bad = dict(HIT, text="Take 500 mg of paracetamol twice a day.")
    r = await mk(A(intent="medical_question"), GuidanceRAG(bad)).handle(Session(id="t"), "I have a minor burn, what should I do")
    assert r.handover  # output guard rejected the passage


async def test_guidance_mid_booking_resumes_the_flow():
    eng = mk(A(intent="medical_question"))
    s = Session(id="t", state="AWAIT_DEPT", last_prompt="Which department would you like to see?")
    r = await eng.handle(s, "I feel sick and dizzy, what should I do")
    assert r.handover is None and s.state == "AWAIT_DEPT" and say_(r).endswith("Which department would you like to see?")


async def test_llm_offline_common_complaint_uses_the_fixed_interview_not_staff():
    """Free-tier AI keys run out: a COMMON complaint carries on with the fixed yes/no interview (rules + danger questions)."""
    eng = Engine(Settings(), FakeLLM(None), FakeEMR(), GuidanceRAG())
    s = Session(id="t")
    r = await eng.handle(s, "I'm feeling sick and vomiting, what should I do")
    assert r.handover is None and s.state == "AWAIT_SYMPTOM_Q" and r.safety["llm_check"] == "offline"


async def test_llm_offline_unknown_or_risky_symptoms_still_go_to_staff():
    eng = Engine(Settings(), FakeLLM(None), FakeEMR(), GuidanceRAG())
    r = await eng.handle(Session(id="t"), "I found a lump on my neck, what should I do")  # no known interview for this
    assert r.handover
    r = await eng.handle(Session(id="t"), "my baby is vomiting")  # children always go to a person
    assert r.handover
    r = await eng.handle(Session(id="t"), "what tablet should I take for my vomiting")  # medicines never
    assert r.handover
