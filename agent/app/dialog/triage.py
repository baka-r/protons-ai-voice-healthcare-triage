"""Urgency tiers, patient intake (age) and the structured brief handed to staff / doctors.

DRAFT - NOT CLINICALLY APPROVED. The tiers are a triage SUGGESTION, never a diagnosis. Emergency is decided by the red-flag
rules (and the AI safety net), not here: this module can only RAISE urgency, never lower what the rules decided.
"""
from __future__ import annotations

import re
from typing import Any

# lowest -> highest urgency
TIERS = ("self_care", "see_doctor_soon", "same_day", "emergency")
LABELS = {
    "self_care": "Home care",
    "see_doctor_soon": "See a doctor soon",
    "same_day": "Needs same-day attention",
    "emergency": "Emergency",
}


def rank(tier: str | None) -> int:
    return TIERS.index(tier) if tier in TIERS else 1


def at_least(tier: str | None, minimum: str) -> str:
    return tier if rank(tier) >= rank(minimum) else minimum


def clean_tier(value: Any, default: str = "see_doctor_soon") -> str:
    return value if value in TIERS else default


# ---------------------------------------------------------------- age intake
_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUM = r"(\d{1,3}|" + "|".join(_WORDS) + r")"
_NUM_NO_ONE = r"(\d{1,3}|" + "|".join(w for w in _WORDS if w != "one") + r")"  # "I am one of ..." is not an age
_TENS_UNITS = re.compile(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ](one|two|three|four|five|six|seven|eight|nine)\b")
_UNIT_AGE = re.compile(rf"\b{_NUM}(?:[- ]?(?:year|yr)s?)?[- ]?(?:old)?\b")
_STRICT = [  # unambiguous "my age" statements, safe to read from ANY turn
    re.compile(rf"\b(?:i am|i m|i'm|i’m|im|he is|she is|he s|she s|age is|aged|age)\s+{_NUM_NO_ONE}\b(?!\s*(?:days?|weeks?|hours?|minutes?|times|kg|%))"),
    re.compile(rf"\b{_NUM}[- ]?(?:years?|yrs?)[- ]?(?:old|of age)?\b"),
    re.compile(rf"\b{_NUM}\s*(?:y o|yo)\b"),
]
_MONTHS = re.compile(rf"\b{_NUM}[- ]?(months?|weeks?)[- ]?old\b")  # needs "old": "22 weeks pregnant" / "for 3 months" are not ages
_MONTHS_ANY = re.compile(rf"\b{_NUM}[- ]?(months?|weeks?)\b")  # the answer to "how old?": "6 months" is an age, not a duration
_BABY = re.compile(r"\b(baby|infant|newborn|new born)\b")
_TODDLER = re.compile(r"\b(toddler)\b")
_ELDER = re.compile(r"\b(elderly|senior citizen|very old|grandmother|grandfather|grandma|grandpa)\b")


def _num(tok: str) -> int | None:
    if tok.isdigit():
        n = int(tok)
        return n if 0 <= n <= 120 else None
    return _WORDS.get(tok)


def parse_age(norm: str, bare: bool = False) -> int | None:
    """Years, from normalised text. bare=True also accepts a lone number (the answer to 'how old?')."""
    norm = _TENS_UNITS.sub(lambda m: str(_WORDS[m.group(1)] + _WORDS[m.group(2)]), norm)  # "seventy two" -> 72
    if _BABY.search(norm):
        return 0
    m = (_MONTHS_ANY if bare else _MONTHS).search(norm)
    if m and "year" not in norm:
        n = _num(m.group(1))
        return 0 if m.group(2).startswith("week") or n is None or n < 12 else min(n // 12, 120)
    for rx in _STRICT:
        m = rx.search(norm)
        if m:
            n = _num(m.group(1))
            if n is not None:
                return n
    if _TODDLER.search(norm):
        return 2
    if _ELDER.search(norm):
        return 75
    if bare:
        m = _UNIT_AGE.search(norm)
        if m:
            return _num(m.group(1))
    return None


def age_group(age: int | None) -> str:
    if age is None:
        return "unknown"
    if age < 1:
        return "infant"
    if age < 5:
        return "young_child"
    if age < 12:
        return "child"
    if age < 18:
        return "teen"
    if age < 65:
        return "adult"
    return "older"


GROUP_TEXT = {
    "infant": "a baby", "young_child": "a young child", "child": "a child", "teen": "a teenager", "adult": "an adult",
    "older": "an older adult", "unknown": "age not given",
}


def note_age(s: Any, norm: str) -> None:
    """Remember an age the caller volunteers in any turn (strict phrasing only, so '3 days' is never read as an age)."""
    tri = s.triage
    if tri.get("age") is None:
        a = parse_age(norm)
        if a is not None:
            tri["age"], tri["age_group"] = a, age_group(a)


# ---------------------------------------------------------------- tier decision
def adjust_for_age(tier: str, group: str, topic_key: str | None = None) -> tuple[str, str]:
    """(tier, reason). Very young and older patients get a more cautious tier. Never lowers a tier."""
    if group in ("infant", "young_child"):
        if topic_key in ("fever", "vomiting", "diarrhoea"):
            return at_least(tier, "same_day"), "a fever, vomiting or diarrhoea in a young child should be checked by a doctor the same day"
        return at_least(tier, "see_doctor_soon"), "a young child is safer being seen by a doctor"
    if group == "older":
        return at_least(tier, "see_doctor_soon"), "an older adult is safer being seen by a doctor"
    return tier, ""


def decide_symptom_tier(topic_key: str, tags: list[str], group: str) -> tuple[str, list[str]]:
    """Tier after a completed interview with NO danger answer (a danger answer is handled before this)."""
    reasons: list[str] = []
    tier = "self_care"
    if "prolonged" in tags:
        tier = "see_doctor_soon"
        reasons.append("symptoms have lasted longer than is usual for a mild illness")
    tier, why = adjust_for_age(tier, group, topic_key)
    if why:
        reasons.append(why)
    return tier, reasons


def tier_line(tier: str) -> str:
    return {
        "self_care": "For now, looking after yourself at home is usually enough.",
        "see_doctor_soon": "I'd suggest seeing a doctor within the next day or two.",
        "same_day": "I'd suggest a doctor looks at this today.",
    }.get(tier, "")


# ---------------------------------------------------------------- brief for staff / doctors
def brief(s: Any, tier: str | None = None, reasons: list[str] | None = None) -> dict[str, Any]:
    """Structured, de-identified summary: what was asked, what was answered, what was suggested. Safe to show staff."""
    tri = s.triage
    return {
        "topic": tri.get("topic_label") or tri.get("topic") or "",
        "age": tri.get("age"),
        "age_group": tri.get("age_group", "unknown"),
        "answers": list(tri.get("answers", [])),
        "tags": list(tri.get("tags", [])),
        "tier": tier or tri.get("tier"),
        "tier_label": LABELS.get(tier or tri.get("tier") or "", ""),
        "reasons": reasons if reasons is not None else list(tri.get("reasons", [])),
        "language": s.language,
        "source": tri.get("source", "interview"),
    }
