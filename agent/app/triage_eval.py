"""Safety evaluation of the deterministic triage layers (no AI model needed, runs in seconds).

    docker compose exec agent python -m app.triage_eval            # prints a report, exit code 1 if a gate fails
    docker compose exec agent python -m app.triage_eval --json     # machine-readable

Gates (set with the doctors; DRAFT until a clinician signs them off):
  * emergency recall = 100%   every emergency scenario must be caught by the fixed red-flag rules
  * no under-triage           an interview may never return a lower urgency than the expectation
  * every interview danger question hands over to staff
  * medicine / dose requests are never left to the bot (strict-medical rule)
  * false alarms on ordinary hospital questions are reported (target: 0 in the control set)
What this does NOT test: the wording or medical quality of AI-written answers (needs doctor review in the staff console).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.config import Settings
from app.dialog import rules, symptoms, triage
from app.dialog.engine import Engine
from app.dialog.session import Session
from app.safety.redflags import scan_red_flags
from app.safety.text import normalize

SCENARIOS = Path(__file__).resolve().parent.parent / "seed" / "triage_scenarios.json"


class _NoLLM:
    enabled = False


def _engine() -> Engine:
    return Engine(Settings(), _NoLLM(), None, None)  # interview + tier logic only: no model, no EMR, no documents


async def _run_interview(topic: symptoms.Topic, age_reply: str, answers: list[str], eng: Engine) -> tuple[str, str | None]:
    """Drive the real interview. Returns ("handover" | "result", tier)."""
    s = Session(id="eval")
    r = eng._start_symptom_interview(s, topic)
    if s.flow["idx"] < 0:
        r = await eng._symptom_answer(s, normalize(age_reply))
    for a in answers:
        if r.handover:
            break
        r = await eng._symptom_answer(s, normalize(a))
    if r.handover:
        return "handover", (r.triage or {}).get("tier")
    return "result", (r.triage or {}).get("tier")


def _benign_answers(topic: symptoms.Topic) -> list[str]:
    """Answers that trigger no danger and no 'prolonged' tag."""
    out = []
    for q in topic.questions:
        if q.danger_if:
            out.append("no" if q.danger_if == "yes" else "yes")
        else:
            out.append("no" if q.tag_if_yes == "prolonged" else "no")
    return out


async def evaluate() -> dict:
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    eng = _engine()
    res: dict = {"failures": [], "counts": {}}

    def fail(kind: str, what: str) -> None:
        res["failures"].append({"kind": kind, "case": what})

    # 1. emergencies must be caught by the rules
    em = data["emergency"]
    missed = [t for t in em if scan_red_flags(t) is None]
    for t in missed:
        fail("emergency_missed", t)
    res["emergency_recall"] = round(1 - len(missed) / len(em), 4)
    res["counts"]["emergency"] = len(em)

    # 2. ordinary questions must not raise an alarm
    ctl = data["controls_not_emergency"]
    false_alarms = [t for t in ctl if scan_red_flags(t) is not None]
    for t in false_alarms:
        fail("false_alarm", t)
    res["false_alarm_rate"] = round(len(false_alarms) / len(ctl), 4)
    res["counts"]["controls"] = len(ctl)

    # 3. medicine / dose requests must be recognised
    med = data["medicine_requests_must_not_be_answered_by_the_bot"]
    leaked = [t for t in med if not rules.is_strict_medical(normalize(t))]
    for t in leaked:
        fail("medicine_request_not_blocked", t)
    res["medicine_block_rate"] = round(1 - len(leaked) / len(med), 4)
    res["counts"]["medicine"] = len(med)

    # 4. age intake
    bad_age = [c["say"] for c in data["ages"] if triage.parse_age(normalize(c["say"])) != c["age"]]
    for t in bad_age:
        fail("age_parse", t)
    res["counts"]["ages"] = len(data["ages"])

    # 5. interviews generated from the topic definitions
    n_int = under = 0
    for topic in symptoms.TOPICS:
        # 5a. every danger question hands over
        for i, q in enumerate(topic.questions):
            if not q.danger_if:
                continue
            ans = _benign_answers(topic)[:i] + ["yes" if q.danger_if == "yes" else "no"]
            kind, _ = await _run_interview(topic, "30", ans, eng)
            n_int += 1
            if kind != "handover":
                fail("danger_question_did_not_hand_over", f"{topic.key}: {q.text}")
        # 5b. an adult with benign answers gets home care
        kind, tier = await _run_interview(topic, "30", _benign_answers(topic), eng)
        n_int += 1
        if kind != "result" or tier != "self_care":
            fail("benign_adult_not_home_care", f"{topic.key}: got {kind}/{tier}")
        # 5c. a prolonged answer is never home care
        for i, q in enumerate(topic.questions):
            if q.tag_if_yes == "prolonged":
                ans = _benign_answers(topic)
                ans[i] = "yes"
                kind, tier = await _run_interview(topic, "30", ans, eng)
                n_int += 1
                if kind == "result" and triage.rank(tier) < triage.rank("see_doctor_soon"):
                    under += 1
                    fail("under_triage", f"{topic.key}: prolonged symptoms got {tier}")
        # 5d. an older adult or a baby is never home care
        for age, floor in (("78", "see_doctor_soon"), ("6 months", "see_doctor_soon")):
            kind, tier = await _run_interview(topic, age, _benign_answers(topic), eng)
            n_int += 1
            if kind == "result" and triage.rank(tier) < triage.rank(floor):
                under += 1
                fail("under_triage", f"{topic.key}: age {age} got {tier}")
        if topic.key in ("fever", "vomiting", "diarrhoea"):
            kind, tier = await _run_interview(topic, "6 months", _benign_answers(topic), eng)
            n_int += 1
            if kind == "result" and triage.rank(tier) < triage.rank("same_day"):
                under += 1
                fail("under_triage", f"{topic.key}: a baby got {tier}")
    res["counts"]["interviews"] = n_int
    res["under_triage"] = under
    res["topics"] = len(symptoms.TOPICS)
    res["clinician_corrections_pending"] = len(data.get("clinician_corrections", []))

    gates = {
        "emergency_recall_100": res["emergency_recall"] == 1.0,
        "no_under_triage": under == 0,
        "danger_questions_hand_over": not any(f["kind"] == "danger_question_did_not_hand_over" for f in res["failures"]),
        "medicine_requests_blocked": res["medicine_block_rate"] == 1.0,
        "no_false_alarms_in_controls": res["false_alarm_rate"] == 0.0,
        "age_intake_correct": not bad_age,
    }
    res["gates"] = gates
    res["passed"] = all(gates.values())
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    res = asyncio.run(evaluate())
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        c = res["counts"]
        print(f"Triage safety evaluation (DRAFT scenarios, not clinician-approved)\n"
              f"  topics: {res['topics']}   emergencies: {c['emergency']}   controls: {c['controls']}   medicine requests: {c['medicine']}   interviews run: {c['interviews']}")
        print(f"  emergency recall:   {res['emergency_recall'] * 100:.1f}%")
        print(f"  false alarms:       {res['false_alarm_rate'] * 100:.1f}%")
        print(f"  medicine blocked:   {res['medicine_block_rate'] * 100:.1f}%")
        print(f"  under-triage:       {res['under_triage']}")
        for k, ok in res["gates"].items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {k}")
        for f in res["failures"][:40]:
            print(f"    - {f['kind']}: {f['case']}")
        print("RESULT:", "PASSED" if res["passed"] else "FAILED")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
