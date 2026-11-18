"""Urgency tiers, age intake, symptom interview with intake, doctor-mode tier, and the safety evaluation gates."""
import pytest

from app.config import Settings
from app.dialog import symptoms, triage
from app.dialog.engine import Engine
from app.dialog.session import Session
from app.safety.text import normalize
from app.services.doctor import DoctorReply, parse_doctor
from app import triage_eval
from tests.test_engine import FakeEMR, FakeLLM, FakeRAG, A


def mk(doctor=None):
    return Engine(Settings(), FakeLLM(A(intent="medical_question")), FakeEMR(), FakeRAG([]), None, doctor)


async def say(eng, s, text):
    return await eng.handle(s, text)


# ---------------------------------------------------------------- age
@pytest.mark.parametrize("text,age", [
    ("I am 45", 45), ("my son is 6 years old", 6), ("she is 3 months old", 0), ("I'm thirty", 30), ("he is seventy two", 72),
    ("my baby has a fever", 0), ("I have had it for 3 days", None), ("I'm 22 weeks pregnant", None), ("I am one of the patients", None),
])
def test_parse_age(text, age):
    assert triage.parse_age(normalize(text)) == age


def test_bare_number_only_in_the_age_question():
    assert triage.parse_age("45") is None and triage.parse_age("45", bare=True) == 45


def test_age_groups():
    assert [triage.age_group(a) for a in (None, 0, 3, 8, 15, 40, 80)] == ["unknown", "infant", "young_child", "child", "teen", "adult", "older"]


def test_tier_never_lowers_and_orders():
    assert triage.at_least("emergency", "same_day") == "emergency" and triage.at_least("self_care", "same_day") == "same_day"
    assert triage.rank("self_care") < triage.rank("see_doctor_soon") < triage.rank("same_day") < triage.rank("emergency")


# ---------------------------------------------------------------- interview with intake
async def test_interview_asks_age_first_then_questions_and_ends_with_a_tier():
    eng, s = mk(), Session(id="t")
    r = await say(eng, s, "I have a fever")
    assert s.state == "AWAIT_SYMPTOM_Q" and "how old" in " ".join(x.text for x in r.lines).lower()
    r = await say(eng, s, "30")
    assert s.triage["age"] == 30 and s.triage["age_group"] == "adult"
    for ans in ("no", "no", "no", "no"):
        r = await say(eng, s, ans)
    assert r.triage and r.triage["tier"] == "self_care" and r.triage["answers"]
    assert s.state == "IDLE"


async def test_age_already_given_is_not_asked_again():
    eng, s = mk(), Session(id="t")
    await say(eng, s, "I'm 40 and I have a headache")
    assert s.triage["age"] == 40
    r = await say(eng, s, "I have a headache")
    assert "how old" not in " ".join(x.text for x in r.lines).lower()


async def test_unclear_age_is_asked_once_then_interview_continues_cautiously():
    eng, s = mk(), Session(id="t")
    await say(eng, s, "I have a fever")
    r = await say(eng, s, "umm not sure")
    assert s.flow["idx"] == -1 and "rough age" in " ".join(x.text for x in r.lines).lower()
    r = await say(eng, s, "still not sure")
    assert s.flow["idx"] == 0 and s.triage.get("age") is None


async def test_danger_answer_hands_over_with_same_day_brief():
    eng, s = mk(), Session(id="t")
    await say(eng, s, "I have a bad headache")
    await say(eng, s, "40")
    r = await say(eng, s, "yes")  # started suddenly and severely
    assert r.handover and r.handover.urgency == "urgent" and r.triage["tier"] == "same_day"


async def test_prolonged_symptoms_and_older_age_raise_the_tier():
    eng, s = mk(), Session(id="t")
    await say(eng, s, "I have a cough")
    await say(eng, s, "30")
    await say(eng, s, "no")
    await say(eng, s, "no")
    r = await say(eng, s, "yes")  # more than two weeks
    assert r.triage["tier"] == "see_doctor_soon"
    eng, s = mk(), Session(id="t")
    await say(eng, s, "I have a cough")
    await say(eng, s, "80")
    for a in ("no", "no", "no"):
        r = await say(eng, s, a)
    assert r.triage["tier"] == "see_doctor_soon"


async def test_baby_with_fever_is_same_day():
    tier, _ = triage.decide_symptom_tier("fever", [], "infant")
    assert tier == "same_day"


# ---------------------------------------------------------------- doctor mode
def test_doctor_urgency_defaults_and_emergency_is_never_lowered():
    base = {"reply": "x", "stage": "assessment", "emergency": False, "emergency_reason": ""}
    assert parse_doctor(base)["urgency"] == "see_doctor_soon"
    assert parse_doctor({**base, "urgency": "bogus"})["urgency"] == "see_doctor_soon"
    p = parse_doctor({**base, "urgency": "emergency"})
    assert p["emergency"] is True and p["emergency_reason"]
    assert parse_doctor({**base, "urgency": "self_care"})["emergency"] is False


class FakeDoctor:
    available = True

    def __init__(self, *replies):
        self.replies = list(replies)
        self.known = None

    async def advise(self, history, latest, label, turns, known=None):
        self.known = known
        return self.replies.pop(0) if self.replies else None


async def test_doctor_assessment_carries_a_tier_and_age_makes_it_stricter():
    d = FakeDoctor(DoctorReply("This could be a mild stomach bug. Rest and sip fluids.", "assessment", False, "", [], "self_care"))
    eng, s = mk(d), Session(id="t")
    r = await say(eng, s, "my son is 4 years old and has been vomiting")
    assert d.known and d.known["age"] == 4
    assert r.triage and r.triage["tier"] == "same_day"  # a young child with vomiting is never "home care"
    assert r.triage["source"] == "doctor_mode"


async def test_doctor_asking_stage_has_no_tier_yet():
    d = FakeDoctor(DoctorReply("How long has it been going on?", "asking", False, "", [], "see_doctor_soon"))
    eng, s = mk(d), Session(id="t")
    r = await say(eng, s, "I have a headache since morning and feel tired")
    assert r.triage is None


# ---------------------------------------------------------------- topics
def test_every_topic_has_a_danger_question_and_guidance_text():
    for t in symptoms.TOPICS:
        assert any(q.danger_if for q in t.questions), f"{t.key} has no danger question"
        assert t.default_cause and t.dept
    assert len(symptoms.TOPICS) >= 18


def test_new_topics_are_matched():
    for text, key in [("my back hurts", "back pain"), ("I have a toothache", "toothache"), ("burning when I pass urine", "painful urination"),
                      ("I can't sleep at night", "poor sleep"), ("I am constipated", "constipation"), ("my ear hurts", "ear pain"),
                      ("my eyes are red and itchy", "eye irritation"), ("I'm always tired", "tiredness"), ("joint pain in my knee", "joint pain")]:
        t = symptoms.match_topic(normalize(text))
        assert t is not None and t.key == key, (text, t and t.key)


# ---------------------------------------------------------------- the safety evaluation itself
async def test_triage_safety_gates_pass():
    res = await triage_eval.evaluate()
    assert res["passed"], res["failures"][:10]
    assert res["emergency_recall"] == 1.0 and res["under_triage"] == 0
