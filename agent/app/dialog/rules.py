"""Deterministic NLU helpers: intents, yes/no, names, dates, times, departments."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import dateparser
from rapidfuzz import fuzz

from app.config import get_settings
from app.safety.text import normalize, tokens

YES_TOKENS = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "correct", "right", "confirm", "confirmed",
    "absolutely", "definitely", "haan", "han", "ji", "jee", "bilkul", "theek", "thik",
    "جی", "ہاں", "ٹھیک", "بالکل",
}
NO_TOKENS = {
    "no", "nope", "nah", "not", "dont", "don't", "never", "wrong", "nahi", "nahin", "nai", "nhi",
    "نہیں", "نہ", "غلط",
}


def now_local() -> datetime:
    return datetime.now(ZoneInfo(get_settings().tz)).replace(tzinfo=None)


def is_no(norm: str) -> bool:
    t = tokens(norm)
    return bool(t) and len(t) <= 8 and (t[0] in NO_TOKENS or any(x in NO_TOKENS for x in t[:3]))


def is_yes(norm: str) -> bool:
    t = tokens(norm)
    if not t or len(t) > 8 or is_no(norm):
        return False
    if t[0] in YES_TOKENS:
        return True
    return any(p in norm for p in ("go ahead", "that works", "sounds good", "please do", "that's right", "thats right"))


_ADDRESS = re.compile(r"\b(hania|haniya|hanya|hannia|hanyah)\b")
_AREHUMAN = re.compile(
    r"\bare you (a |an )?(human|real|robot|bot|ai|machine|person|actual person|computer|alive)\b"
    r"|\bam i (talking|speaking) (to|with) (a |an )?(human|robot|bot|machine|real person|computer|ai)\b|\bis this (a )?(robot|bot|ai|recording)\b"
)
_IDENTITY = re.compile(
    r"\bwho are you\b|what('s| is) your name|\byour name\b|who am i (speaking|talking) (to|with)|\bwhat are you\b|"
    r"introduce yourself|what can you do|what do you do|how can you help|tell me about yourself|\bapna naam\b|aap kaun"
)
_THANKS = re.compile(r"^(thanks|thank you|thank you so much|thanks a lot|many thanks|thanks so much|shukriya|shukria|jazak allah)$")
_SMALL = re.compile(r"^(how are you|how are you doing|how's it going|how do you do|what's up|kaise ho|kese ho|how r u)( today)?$")
_REPEAT = re.compile(
    r"\b(repeat|say (that )?again|come again|pardon|what did you say|didn't (hear|catch|get)|can you say that|once more|dobara)\b|^(sorry|what|huh|eh)$"
)
_HUMAN = re.compile(
    r"(talk|speak|connect|transfer|put me|get me|let me|want|need).{0,30}"
    r"(human|person|someone|somebody|staff|agent|representative|operator|receptionist|reception|front desk|help ?desk|nurse|doctor|real person)"
    r"|\b(human|real person|operator|receptionist|insaan)\b|kisi se baat|staff se baat|baat karni|کسی سے بات|انسان|عملے"
)
_GOODBYE = re.compile(
    r"^(bye|goodbye|good bye|that'?s all|that is all|no thanks?|no thank you|nothing else|nothing more|"
    r"thank you bye|thanks bye|khuda hafiz|allah hafiz|alvida|thats all|that'?s it|i'?m done|im done)$|^(allah|khuda) hafiz"
)
_GREETING = re.compile(
    r"^(hi|hello|hey|salam|assalam o alaikum|assalamualaikum|assalamu alaikum|good (morning|afternoon|evening)|"
    r"السلام علیکم|ہیلو)( there| aria)?$"
)
_NEVERMIND = re.compile(r"\b(never ?mind|forget it|forget about it|leave it|stop|start over|go back)\b|chor do|rehne do")
_BOOK = re.compile(
    r"(book|make|schedule|set up|fix|arrange|need|want|get|take|like).{0,30}\b(appointment|appt|apointment|visit|slot|consultation|check ?up)\b"
    r"|appointment (for|with|please)|see a (doctor|specialist|consultant)|(appointment|apointment).{0,12}(chahiye|lena|book|karni|karna)|اپوائنٹمنٹ"
)
_RESCHEDULE = re.compile(
    r"(re ?schedule|change|move|shift|postpone|push back).{0,30}(appointment|visit|booking|slot)|appointment.{0,15}(change|move|re ?schedule)"
)
_CANCEL = re.compile(r"(cancel|call off|delete|remove).{0,30}(appointment|visit|booking|slot)|cancel (it|my)|\bcancel\b")
_INFO = re.compile(
    r"\b(opd|visiting|visitors?|pharmacy|lab|laboratory|parking|location|address|where is|where are you|directions|"
    r"how (do i|to) (get|reach)|open|close|closing|timings?|hours|fees?|charges|cost|insurance|bring|prepare|preparation|"
    r"documents?|departments?|services?|cnic|policy|rules|cafeteria|wifi|facilities|facility|bill|billing|pay|payment|payments)\b"
)
_MEDICAL = re.compile(
    r"(what|which) (medicine|medication|drug|tablet|pill|antibiotic|painkiller|syrup|treatment|cure|remedy)s?\b"
    r"|(should|can|could|may) i (take|use|eat|drink|stop|skip|double)\b"
    r"|how (much|many) .{0,20}(mg|tablet|pill|dose|dosage|ml|capsule)"
    r"|\b(dose|dosage|prescription|prescribe)\b"
    r"|is (it|this) (serious|dangerous|cancer|an infection|contagious|normal|safe)"
    r"|what('s| is) (wrong with me|causing)|\bdiagnos\w*|what (disease|illness|condition)|side effects?|home remedy"
    r"|\b(dawai|dawa)\b|konsi (dawai|dawa)|kaun si (dawai|dawa)|دوا|ٹیبلٹ|علاج"
)


_SYMPTOMS = re.compile(
    r"\b(pain|painful|ache|aching|hurts?|bleed\w*|blood|vomit\w*|nausea|nauseous|dizzy|dizziness|faint\w*|fever|rash|"
    r"swell\w*|swollen|sweat\w*|numb|numbness|weakness|cough\w*|breath\w*|chest|headache|migraine|infection|injur\w*|wound|"
    r"burn\w*|bite|bitten|seizure|confus\w*|palpitation\w*|cramp\w*|diarrh\w*|lump|symptom\w*|sick|unwell|ill)\b"
    r"|dard|bukhar|khoon|ulti|chakkar|dard|ٹھیک نہیں|درد|بخار|خون|الٹی|چکر"
)


def mentions_symptoms(norm: str) -> bool:
    return bool(_SYMPTOMS.search(norm))


_LEAD = re.compile(r"^(?:(?:hi|hello|hey|salam|excuse me|um|uh|well|so|ok|okay|please|sorry|listen|quickly)\s+)+")
_TRAIL = re.compile(r"(?:\s+(?:please|now|today|urgently|immediately|right now|thanks))+$")


def _core(norm: str) -> str:
    """Strip polite filler so anchored phrases ('thanks', 'bye', 'how are you') still match."""
    c = _TRAIL.sub("", _LEAD.sub("", norm)).strip()
    return c or norm


# Requests that must ALWAYS go to a human, never to self-care guidance: medicines, doses, diagnosis, prescriptions.
_MED_STRICT = re.compile(
    r"(what|which) (medicine|medication|drug|tablet|pill|antibiotic|painkiller|syrup|treatment|cure|remedy)s?\b"
    r"|(should|can|could|may) i (take|use|stop|skip|double)\b|what (should|can|do) i (give|use|take)\b|\bgive (her|him|them|it)\b"
    r"|how (much|many) .{0,20}(mg|tablet|pill|dose|dosage|ml|capsule)|\b(dose|dosage|prescription|prescribe)\b|\bdiagnos\w*"
    r"|what('s| is) wrong with me|what (disease|illness|condition)|side effects?|home remedy|\bcancer\b|\btumou?r\b"
    r"|\b(pills?|tablets?|capsules?|medications?|medicines?|drugs?|antibiotics?|injections?|insulin|inhalers?)\b"
    r"|\b(dawai|dawa)\b|konsi|kaun si|دوا|ٹیبلٹ|علاج"
)
# Anything about babies, children, pregnancy or frail relatives is not handled by generic guidance.
_VULNERABLE = re.compile(
    r"\b(baby|babies|infant|newborn|toddler|child|children|kid|kids|son|daughter|pregnan\w*|expecting|elderly|grandfather|grandmother|grandpa|grandma|bacha|bachi|bachay)\b"
)


def is_strict_medical(norm: str) -> bool:
    return bool(_MED_STRICT.search(norm) or _VULNERABLE.search(norm))


def rule_intent(norm: str) -> str | None:
    norm = _ADDRESS.sub(" ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    if not norm:
        return None
    core = _core(norm)
    if _MEDICAL.search(norm):
        return "medical_question"
    if _AREHUMAN.search(norm):
        return "are_you_human"
    if _IDENTITY.search(norm):
        return "identity_question"
    if _HUMAN.search(norm):
        return "talk_to_human"
    if _RESCHEDULE.search(norm):
        return "reschedule_appointment"
    if _CANCEL.search(norm):
        return "cancel_appointment"
    if _BOOK.search(norm):
        return "book_appointment"
    if _GOODBYE.search(core):
        return "goodbye"
    if _THANKS.search(core):
        return "thanks"
    if _SMALL.search(core):
        return "smalltalk"
    if _REPEAT.search(core):
        return "repeat_request"
    if _GREETING.search(norm):
        return "greeting"
    if _INFO.search(norm):
        return "hospital_info"
    return None


def wants_never_mind(norm: str) -> bool:
    return bool(_NEVERMIND.search(norm))


# ---------------------------------------------------------------- names / dob
_NAME_PREFIX = re.compile(
    r"^(?:(?:hi|hello|salam|assalam o alaikum|assalamualaikum)\s+)?"
    r"(?:my full name is|my name is|my name's|the name is|this is|i am|i'm|it's|its|name is|mera naam|mera nam|main|mai|میرا نام)\s+"
)
_DOB_SPLIT = re.compile(r"\b(?:and\s+)?(?:my\s+)?(?:date of birth|dob|d o b|born on|born|birthday|birth date)\b(?:\s+is)?")


def split_name_dob(norm: str) -> tuple[str, str]:
    """'my name is ayesha khan and my date of birth is 12 march 1990' -> (name part, dob part)."""
    parts = _DOB_SPLIT.split(norm, maxsplit=1)
    name_part = parts[0].strip()
    dob_part = parts[1].strip() if len(parts) > 1 else ""
    return name_part, dob_part


_NOT_NAME = {
    "appointment", "book", "want", "need", "cancel", "schedule", "reschedule", "hospital", "doctor",
    "timings", "hours", "help", "emergency", "what", "where", "how", "when", "why", "can", "could",
    "would", "should", "the", "staff", "person", "human", "operator", "yes", "no", "okay", "ok",
}


def extract_name(name_part: str) -> str | None:
    t = _NAME_PREFIX.sub("", name_part.strip())
    t = re.sub(r"\b(and|please|sir|madam|thanks|thank you)\b", " ", t)
    words = [w for w in re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", t, flags=re.UNICODE) if len(w) >= 2]
    if not 1 <= len(words) <= 5 or any(w in _NOT_NAME for w in words):
        return None
    return " ".join(w.capitalize() for w in words)


def parse_dob(text: str) -> date | None:
    if not text.strip():
        return None
    dt = dateparser.parse(
        text,
        languages=["en"],
        settings={"PREFER_DATES_FROM": "past", "DATE_ORDER": "DMY", "STRICT_PARSING": False},
    )
    if not dt:
        return None
    d = dt.date()
    today = now_local().date()
    if d.year < 1900 or d >= today:
        return None
    return d


# ---------------------------------------------------------------- date / time
def parse_date(text: str) -> date | None:
    base = now_local()
    dt = dateparser.parse(
        text,
        languages=["en"],
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": base, "DATE_ORDER": "DMY"},
    )
    return dt.date() if dt else None


def valid_booking_date(d: date) -> bool:
    today = now_local().date()
    return today <= d <= today + timedelta(days=60)


def parse_time(text: str) -> str | None:
    """Return 'HH:MM' if the text clearly states a clock time."""
    if not re.search(r"\d|noon|midnight", text):
        return None
    dt = dateparser.parse(text, languages=["en"], settings={"PREFER_DATES_FROM": "future"})
    if not dt:
        return None
    return dt.strftime("%H:%M")


def pick_slot(norm: str, offered: list[str], llm_time: str | None) -> str | None:
    if not offered:
        return None
    if llm_time and llm_time in offered:
        return llm_time
    t = parse_time(norm)
    if t and t in offered:
        return t
    words = set(tokens(norm))
    if words & {"first", "earliest", "earlier", "1st"}:
        return offered[0]
    if words & {"second", "2nd"} and len(offered) > 1:
        return offered[1]
    if words & {"third", "3rd"} and len(offered) > 2:
        return offered[2]
    if words & {"last", "latest"}:
        return offered[-1]
    if "morning" in words:
        return next((s for s in offered if s < "12:00"), None)
    if "afternoon" in words:
        return next((s for s in offered if "12:00" <= s < "16:00"), None)
    if "evening" in words:
        return next((s for s in offered if s >= "16:00"), None)
    if len(offered) == 1 and is_yes(norm):
        return offered[0]
    return None


# ---------------------------------------------------------------- departments
def match_department(norm: str, departments: list[dict]) -> dict | None:
    """departments: [{'id','name','aliases':[...]}]. Fuzzy, word-level."""
    toks = tokens(norm)
    grams = list(toks)
    grams += [" ".join(toks[i : i + 2]) for i in range(len(toks) - 1)]
    grams += [" ".join(toks[i : i + 3]) for i in range(len(toks) - 2)]
    best: tuple[float, dict | None] = (0.0, None)
    for dept in departments:
        for alias in [dept["name"].lower(), *[a.lower() for a in dept.get("aliases", [])]]:
            cutoff = 92 if len(alias) <= 3 else 84
            for g in grams:
                if abs(len(g) - len(alias)) > 4:
                    continue
                score = fuzz.ratio(g, alias)
                if score >= cutoff and score > best[0]:
                    best = (score, dept)
    return best[1]


# ---------------------------------------------------------------- formatting
def fmt_time(hhmm: str) -> str:
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def fmt_date(d: date) -> str:
    return f"{d.strftime('%A')}, {d.day} {d.strftime('%B')}"


def join_list(items: list[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
