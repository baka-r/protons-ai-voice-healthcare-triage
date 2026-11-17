"""Output guard: nothing dynamic is spoken unless it passes this check.

Fixed, reviewed scripts are marked trusted and skip the guard. Everything else
(retrieved document text, any LLM-phrased text) must contain no dosage, drug or
diagnosis language, otherwise it is replaced by a human handover.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_DRUGS = (
    "paracetamol|acetaminophen|panadol|ibuprofen|brufen|aspirin|disprin|amoxicillin|augmentin|"
    "azithromycin|antibiotics?|insulin|metformin|steroids?|prednisolone|morphine|tramadol|"
    "diclofenac|omeprazole|painkillers?|sedatives?|antidepressants?|opioids?"
)
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("dosage", re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|ml|iu|units?)\b", re.I)),
    ("dosing_instruction", re.compile(r"\b(take|taking|use|apply)\b.{0,30}\b(tablets?|pills?|capsules?|syrup|doses?)\b", re.I)),
    ("drug_name", re.compile(rf"\b({_DRUGS})\b", re.I)),
    ("diagnosis", re.compile(r"\byou (probably|likely|may|might|could|definitely|certainly) (have|be suffering)\b", re.I)),
    ("diagnosis", re.compile(r"\byou (are suffering|suffer from)\b", re.I)),
    ("diagnosis", re.compile(r"\byou have (an? |some )?(infection|disease|cancer|diabetes|condition|virus|disorder|syndrome|tumou?r|fracture|flu|covid)\b", re.I)),
    ("diagnosis", re.compile(r"\bit('s| is) (probably|likely|most likely|possibly)\b", re.I)),
    ("diagnosis", re.compile(r"\bdiagnos(is|ed|e)\b", re.I)),
    ("treatment_advice", re.compile(r"\byou should (take|stop taking|start taking)\b", re.I)),
]


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str | None = None


def check_output(text: str) -> GuardResult:
    for name, rx in _PATTERNS:
        if rx.search(text):
            return GuardResult(False, name)
    return GuardResult(True)
