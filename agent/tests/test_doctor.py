"""Doctor-style conversation: follow-up questions, possible explanations, hard limits."""
from app.config import Settings
from app.dialog.engine import Engine
from app.dialog.session import Session
from app.services.doctor import DoctorReply
from tests.test_engine import FakeEMR, FakeLLM, FakeRAG, A


class FakeDoctor:
    available = True

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    async def advise(self, history, latest, label, turns, known=None):
        self.calls.append((latest, label, turns))
        self.known = known
        return self.replies.pop(0) if self.replies else None


def R(reply, stage="asking", emergency=False, reason=""):
    return DoctorReply(reply, stage, emergency, reason, [{"title": "Nausea and Vomiting", "source": "MedlinePlus", "url": "https://medlineplus.gov/x"}])


def mk(doctor, analysis=None):
    return Engine(Settings(), FakeLLM(analysis or A(intent="medical_question")), FakeEMR(), FakeRAG([]), None, doctor)


def said(r):
    return " ".join(x.text for x in r.lines)


async def test_user_asks_for_advice_and_is_not_sent_to_staff():
    eng, s = mk(FakeDoctor(R("I'm sorry you feel that way. How long have you been vomiting?"))), Session(id="t")
    r = await eng.handle(s, "im feeling sick im like ahving vomit what to do ? its not for diagonose?")
    assert r.handover is None and s.state == "AWAIT_DOCTOR" and r.intent == "doctor_chat"
    t = said(r)
    assert "testing agent and not a professional doctor" in t and "How long" in t


async def test_disclaimer_only_once_and_conversation_continues_to_assessment():
    doc = FakeDoctor(R("How long?"), R("Any fever?"), R("This could be a stomach bug. Rest and sip fluids.", "assessment"))
    eng, s = mk(doc), Session(id="t")
    r1 = await eng.handle(s, "I feel sick and vomiting")
    r2 = await eng.handle(s, "since yesterday")
    r3 = await eng.handle(s, "no fever")
    assert "professional doctor" in said(r1) and "professional doctor" not in said(r2)
    assert r3.handover is None and s.state == "IDLE" and "see a doctor" in said(r3) and s.doctor_turns == 0
    assert [c[2] for c in doc.calls] == [0, 1, 2]


async def test_emergency_in_doctor_reply_escalates():
    eng, s = mk(FakeDoctor(R("Please get help now.", "assessment", True, "blood in vomit"))), Session(id="t")
    r = await eng.handle(s, "I feel sick and I'm vomiting a bit")
    assert r.handover and r.handover.urgency == "emergency" and r.handover.source == "llm"


async def test_unsafe_model_text_is_never_spoken():
    for bad in ("Take 500 mg of paracetamol.", "You probably have gastroenteritis.", "It's most likely food poisoning."):
        eng, s = mk(FakeDoctor(R(bad, "assessment"))), Session(id="t")
        r = await eng.handle(s, "I feel sick and I'm vomiting, what should I do")
        assert bad not in said(r), bad  # fell back to the fixed interview, never spoke the unsafe text


async def test_doctor_unavailable_falls_back_to_fixed_interview():
    eng, s = mk(FakeDoctor()), Session(id="t")  # advise() returns None
    r = await eng.handle(s, "I feel sick and I'm vomiting, what should I do")
    assert s.state == "AWAIT_SYMPTOM_Q" and r.handover is None


async def test_medicine_question_goes_to_doctor_mode_not_staff():
    eng, s = mk(FakeDoctor(R("A doctor or pharmacist should advise on that. Meanwhile rest and sip water.", "assessment"))), Session(id="t")
    r = await eng.handle(s, "what should I take for vomiting")
    assert r.handover is None and "pharmacist" in said(r)


async def test_red_flag_rules_still_win_over_doctor_mode():
    doc = FakeDoctor(R("fine"))
    eng, s = mk(doc), Session(id="t")
    r = await eng.handle(s, "I'm vomiting blood")
    assert r.handover and r.handover.source == "rules" and not doc.calls


async def test_leaving_doctor_mode_for_booking_and_info():
    eng, s = mk(FakeDoctor(R("How long?")), A(intent="book_appointment")), Session(id="t")
    await eng.handle(s, "I feel sick and vomiting")
    r = await eng.handle(s, "actually I'd like to book an appointment")
    assert s.state == "AWAIT_NAME"


async def test_ai_check_marking_info_request_medical_does_not_hand_over_when_doctor_mode_is_on():
    eng, s = mk(FakeDoctor()), Session(id="t")
    late = eng.late_action(s, A(intent="medical_question"), "what are your timings")
    assert late is None
