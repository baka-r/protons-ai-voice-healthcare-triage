"""Latency design: benign turns are answered from the rules at once; the AI safety net runs in parallel and may interrupt."""
import asyncio

from app.config import Settings
from app.dialog.engine import Engine
from app.dialog.session import Session
from app.services.llm import Analysis
from tests.test_engine import FakeEMR, FakeRAG, A

HIT = {"chunk_id": "hospital-hours:v2:0", "text": "Our outpatient clinics are open Monday to Saturday from 9 AM to 5 PM.", "title": "Hours", "version": 2, "score": 0.9}


class SlowLLM:
    enabled = True

    def __init__(self, analysis, delay=0.3):
        self.analysis, self.delay, self.calls = analysis, delay, 0

    async def analyze(self, **kw):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return self.analysis


def mk(llm, hits=None):
    return Engine(Settings(), llm, FakeEMR(), FakeRAG(hits if hits is not None else [HIT]))


async def test_benign_info_answers_before_the_llm_returns():
    llm = SlowLLM(A(intent="hospital_info"), delay=2.0)
    eng, s = mk(llm), Session(id="t")
    t0 = asyncio.get_running_loop().time()
    r = await eng.handle(s, "what are your OPD timings")
    took = asyncio.get_running_loop().time() - t0
    assert took < 0.5, f"should not wait for the 2s LLM, took {took:.2f}s"
    assert r.pending_analysis is not None and HIT["text"] in " ".join(x.text for x in r.lines)
    r.pending_analysis.cancel()


async def test_parallel_check_can_interrupt_with_emergency():
    llm = SlowLLM(A(intent="other", red_flag=True, red_flag_reason="possible stroke"))
    eng, s = mk(llm), Session(id="t")
    r = await eng.handle(s, "what are the visiting hours")
    a = await r.pending_analysis
    late = eng.late_action(s, a, "what are the visiting hours")
    assert late and late.handover and late.handover.urgency == "emergency" and late.handover.source == "llm"


async def test_parallel_check_can_flag_medical_request():
    eng, s = mk(SlowLLM(A(intent="medical_question"))), Session(id="t")
    r = await eng.handle(s, "what are your OPD timings")
    late = eng.late_action(s, await r.pending_analysis, "what are your OPD timings")
    assert late and late.handover.reason == "medical_advice_request"


async def test_no_interruption_when_check_is_clean():
    eng, s = mk(SlowLLM(A(intent="hospital_info"))), Session(id="t")
    r = await eng.handle(s, "what are your OPD timings")
    assert eng.late_action(s, await r.pending_analysis, "what are your OPD timings") is None


async def test_unavailable_check_with_symptom_words_escalates():
    eng, s = mk(SlowLLM(None)), Session(id="t")
    assert eng.late_action(s, None, "what are your timings, I have a fever") is not None
    assert eng.late_action(s, None, "what are your timings") is None


async def test_symptom_mentions_never_take_the_fast_path():
    llm = SlowLLM(A(intent="hospital_info"), delay=0.2)
    eng, s = mk(llm), Session(id="t")
    r = await eng.handle(s, "what are your timings, I have a fever")
    assert r.pending_analysis is None  # waited for the model instead


async def test_uncertain_info_waits_for_the_model_and_its_rewrite():
    llm = SlowLLM(A(intent="hospital_info", info_query="opd timings"), delay=0.1)
    eng, s = mk(llm, hits=[]), Session(id="t")  # no retrieval hit from the raw words -> not confident
    r = await eng.handle(s, "what are your OPD timings")
    assert r.pending_analysis is None and llm.calls >= 1


async def test_short_slot_answers_skip_the_llm_entirely():
    llm = SlowLLM(A(intent="provide_info", department="Cardiology"), delay=2.0)
    eng = mk(llm)
    s = Session(id="t", state="AWAIT_DEPT", verified=True, patient={"id": "P-1001", "name": "Ayesha Khan"})
    t0 = asyncio.get_running_loop().time()
    r = await eng.handle(s, "cardiology please")
    assert asyncio.get_running_loop().time() - t0 < 0.5 and s.state == "AWAIT_DATE" and r.pending_analysis is None


async def test_ai_alone_cannot_turn_an_info_question_into_a_handover():
    eng, s = mk(SlowLLM(A(intent="talk_to_human"))), Session(id="t")
    r = await eng.handle(s, "what are your OPD timings")
    assert eng.late_action(s, await r.pending_analysis, "what are your OPD timings") is None


async def test_ai_can_still_flag_emergency_on_an_info_style_message():
    eng, s = mk(SlowLLM(A(intent="other", red_flag=True))), Session(id="t")
    r = await eng.handle(s, "what are the visiting hours")
    late = eng.late_action(s, await r.pending_analysis, "what are the visiting hours")
    assert late and late.handover.urgency == "emergency"
