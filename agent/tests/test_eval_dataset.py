"""Regression gate: replay the whole synthetic dataset (~1k cases) through the engine, LLM offline."""
import pytest

from app.evalrun import THRESHOLDS, offline_engine, retrieval_eval, run_case, run_scenarios, summarise
from seed.generate_cases import all_cases


def test_dataset_size_and_integrity():
    cases = all_cases()
    assert len(cases) >= 900
    assert len({c.id for c in cases}) == len(cases)
    assert all(c.text is not None and c.expect for c in cases)


async def test_rules_mode_meets_safety_thresholds(capsys):
    eng = offline_engine()
    results = [await run_case(eng, c, rules_mode=True) for c in all_cases()]
    scenarios = await run_scenarios(offline_engine)
    m, ok = summarise(results, scenarios, None)
    out = capsys.readouterr().out
    assert ok, out[-3500:]
    assert m["safety_recall"] >= THRESHOLDS["safety_recall"]
    assert m["leaks"] == 0


@pytest.mark.parametrize("name", ["book_happy_path", "emergency_mid_booking", "info_interruption_keeps_flow", "persona_mid_flow_resumes"])
async def test_key_scenarios(name):
    res = {r["name"]: r for r in await run_scenarios(offline_engine)}
    assert res[name]["passed"], res[name]["detail"]
