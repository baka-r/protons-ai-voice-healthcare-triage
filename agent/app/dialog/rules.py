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
    "हाँ", "हां", "हा", "जी", "जी हाँ", "जी हां", "ठीक", "बिल्कुल", "बिलकुल", "सही", "ज़रूर", "जरूर", "अच्छा", "ओके", "करिए", "कर दीजिए",
}
NO_TOKENS = {
    "no", "nope", "nah", "not", "dont", "don't", "never", "wrong", "nahi", "nahin", "nai", "nhi",
    "نہیں", "نہ", "غلط",
    "नहीं", "नही", "ना", "मत", "गलत", "नहि",
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


_ADDRESS = re.compile(r"\b(hania|haniya|hanya|hannia|hanyah)\b|हानिया|हनिया|हैनिया")
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
_ROLE_DOCTOR = re.compile(r"\b(i am|i m|i'm|im) (a |an |the )?(doctor|physician|consultant|clinician|nurse|surgeon)\b|\bas a (doctor|physician|nurse|clinician)\b|\bmy patients\b")
_ROLE_QA = re.compile(r"\b(i am|i m|i'm|im) (a |an |the |just )?(qa|tester|testing|test)\b|\bwe are testing\b|\bi am (just )?testing\b|\bthis is a test\b|\btesting (the|this)\b|\bqa test")
_ROLE_OWNER = re.compile(r"\b(i am|i m|i'm|im) (the |a |an )?(owner|founder|ceo|director|manager|administrator)\b|\bmy (hospital|clinic)\b|\bi own (this|the)\b")


def infer_role(norm: str) -> str | None:
    """Who is talking, judged only from what they say about themselves (nobody is asked to pick a role). None = no clue."""
    if _ROLE_DOCTOR.search(norm):
        return "doctor"
    if _ROLE_OWNER.search(norm):
        return "owner"
    if _ROLE_QA.search(norm):
        return "qa"
    return None


_HUMAN_WORDS = re.compile(
    r"(human|person|people|someone|somebody|staff|representative|operator|receptionist|reception|front desk|help ?desk|nurse|agent|insaan|admin)|baat|کسی|انسان|عملے|इंसान|स्टाफ़?|किसी से"
)


def explicit_human_request(norm: str) -> bool:
    """True when the words themselves ask for a person. The AI alone may NOT turn a question like "can I choose my doctor" into a hand-over."""
    return bool(_HUMAN_WORDS.search(norm))


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
    r"documents?|departments?|services?|cnic|policy|rules|cafeteria|wifi|facilities|facility|bill|billing|pay|payment|payments|"
    r"floor|ambulances?|mri|ct scan|x ?ray|ultrasound|scans?|blood bank|physio\w*|wheelchairs?|prayer|atm|discharge|admission|admitted|"
    r"reports?|reception|helpline|phone number|email|complaints?|feedback|vaccin\w*|packages?|interpreters?|photos?|lost property|records?|"
    r"doctors|doctors? (in|for|sees?|available|timings?|schedule|hours)|which doctors?|triage|room types?|sample collection|consultation|follow up|who is the \w+|who are the \w+|cardiologists?|dermatologists?|"
    r"orthopedic\w*|pediatricians?|gynecologists?|clinic days?|sits?|privacy|receipts?|entrances?)\b"
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
    r"burn\w*|bite|bitten|seizure|confus\w*|palpitation\w*|cramp\w*|diarrh\w*|lump|symptom\w*|sick|unwell|ill|"
    r"constipat\w*|fatigue\w*|exhausted|tired|insomnia|itch\w*|toothache|"
    r"(can'?t|cannot) sleep|trouble sleeping|red eyes?|watery eyes?|eyes? (are|is|feel|feels)( very| so| really)? (red|itchy|watery|sore|irritated)|eye (pain|infection|irritation)|(burning|pain)( when| while| during)? (urinat\w*|peeing|pass(ing)? urine))\b"
    r"|dard|bukhar|khoon|ulti|chakkar|dard|ٹھیک نہیں|درد|بخار|خون|الٹی|چکر"
)


_NOT_SYMPTOM = re.compile(r"\bblood (bank|donation|donor|donors|group|test|tests|report|reports|sample|samples)\b|\bchest (xray|x ray|clinic)\b")
_ASK_ABOUT = re.compile(r"\b(ask|asking|know|wondering|enquire|inquire|enquiring) (about|regarding)\b|\binformation (on|about|regarding)\b|\btell me about\b|\bdetails (of|about|on)\b|\bwhat are your\b|\bwhat is the\b")
_BOOK_VERB = re.compile(r"\b(book|schedule|reschedule|cancel|arrange|set up|make an?) ")


def mentions_symptoms(norm: str) -> bool:
    return bool(_SYMPTOMS.search(_NOT_SYMPTOM.sub(" ", norm)))


_LEAD = re.compile(r"^(?:(?:hi|hello|hey|salam|excuse me|um|uh|well|so|ok|okay|please|sorry|listen|quickly)\s+)+")
_TRAIL = re.compile(r"(?:\s+(?:please|now|today|urgently|immediately|right now))+$")


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
    return bool(_MED_STRICT.search(norm) or _VULNERABLE.search(norm) or _HI_MEDICAL.search(norm))


# ---------------------------------------------------------------- Hindi (Devanagari) intents
_DEVA = re.compile(r"[ऀ-ॿ]")
_HI_MEDICAL = re.compile(r"दवा|दवाई|गोली|खुराक|डोज|सिरप|इंजेक्शन|इलाज|नुस्खा|क्या बीमारी|कौन सी बीमारी")
_HI_AREHUMAN = re.compile(r"(क्या )?आप (इंसान|रोबोट|मशीन|असली|एआई|ai)|यह (रोबोट|रिकॉर्डिंग)|इंसान हैं या")
_HI_IDENTITY = re.compile(r"आप कौन|तुम कौन|आपका नाम|तुम्हारा नाम|अपने बारे में|आप क्या कर सकती|आप क्या कर सकते|क्या कर सकती हैं|आप क्या करती")
_HI_HUMAN = re.compile(
    r"(स्टाफ|इंसान|रिसेप्शन|ऑपरेटर|नर्स|डॉक्टर|कर्मचारी).{0,25}(बात|जोड़|मिला)|(बात|जोड़|मिला).{0,25}(स्टाफ|इंसान|रिसेप्शन|ऑपरेटर|नर्स|डॉक्टर|कर्मचारी)|असली इंसान"
)
_HI_RESCHEDULE = re.compile(r"बदल|आगे बढ़ा|टाल|रीशेड्यूल|री शेड्यूल")
_HI_CANCEL = re.compile(r"रद्द|कैंसल|कैंसिल|निरस्त")
_HI_BOOK = re.compile(r"अपॉइंटमेंट|अपोइंटमेंट|एपॉइंटमेंट|अप्वाइंटमेंट|डॉक्टर (को )?(दिखाना|से मिलना)|बुकिंग|बुक कर")
_HI_GOODBYE = re.compile(r"^(अलविदा|बाय|बाय बाय|खुदा हाफिज|अल्लाह हाफिज|बस|बस इतना ही|और कुछ नहीं|कुछ नहीं चाहिए|ठीक है बाय)$")
_HI_THANKS = re.compile(r"^(धन्यवाद|शुक्रिया|शुक्रिया जी|थैंक्यू|थैंक यू|बहुत धन्यवाद|बहुत शुक्रिया|धन्यवाद जी)$")
_HI_SMALL = re.compile(r"^(कैसी हो|कैसे हो|आप कैसी हैं|आप कैसे हैं|कैसी हैं आप)$")
_HI_REPEAT = re.compile(r"दोबारा|फिर से (बोल|बता|कह)|क्या कहा|समझ नहीं आया|एक बार और")
_HI_GREETING = re.compile(r"^(नमस्ते|नमस्कार|हेलो|हैलो|हाय|सलाम|अस्सलाम ?वालेकुम|आदाब)( जी)?( हानिया)?$")
_HI_INFO = re.compile(r"ओपीडी|टाइमिंग|समय क्या|कितने बजे|पार्किंग|पता क्या|कहाँ है|कहां है|फार्मेसी|लैब|विज़िटिंग|विजिटिंग|मिलने का समय|फीस|बीमा|वाईफाई|विभाग|सुविधा|कैफेटेरिया")


def _hi_intent(norm: str) -> str | None:
    if _HI_MEDICAL.search(norm):
        return "medical_question"
    if _HI_AREHUMAN.search(norm):
        return "are_you_human"
    if _HI_IDENTITY.search(norm):
        return "identity_question"
    if _HI_HUMAN.search(norm):
        return "talk_to_human"
    if _HI_BOOK.search(norm):
        return "cancel_appointment" if _HI_CANCEL.search(norm) else "reschedule_appointment" if _HI_RESCHEDULE.search(norm) else "book_appointment"
    if _HI_CANCEL.search(norm) and "अपॉइंट" in norm:
        return "cancel_appointment"
    if _HI_GOODBYE.search(norm):
        return "goodbye"
    if _HI_THANKS.search(norm):
        return "thanks"
    if _HI_SMALL.search(norm):
        return "smalltalk"
    if _HI_REPEAT.search(norm):
        return "repeat_request"
    if _HI_GREETING.search(norm):
        return "greeting"
    if _HI_INFO.search(norm):
        return "hospital_info"
    return None


def rule_intent(norm: str) -> str | None:
    norm = _ADDRESS.sub(" ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    if not norm:
        return None
    if _DEVA.search(norm):
        hi = _hi_intent(norm)
        if hi:
            return hi
    core = _core(norm)
    if _MEDICAL.search(norm):
        return "medical_question"
    if _AREHUMAN.search(norm):
        return "are_you_human"
    if _IDENTITY.search(norm):
        return "identity_question"
    # "I wanted to ask about cardiology doctors / consultation fee": an information question, not a request for a person or a booking
    if _ASK_ABOUT.search(norm) and _INFO.search(norm) and not _BOOK_VERB.search(norm):
        return "hospital_info"
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
        languages=["en", "hi"],
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
        languages=["en", "hi"],
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
    dt = dateparser.parse(text, languages=["en", "hi"], settings={"PREFER_DATES_FROM": "future"})
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


# ---------------------------------------------------------------- caller does NOT want the staff hand-over
_CANCEL_HANDOVER = re.compile(
    r"(don'?t|do not|dont|no need|not necessary|no longer|stop|cancel|never ?mind|forget|without).{0,30}(call|connect|transfer|staff|person|human|nurse|doctor|support|team|anyone|anybody|them|help)"
    r"|(call|connect|transfer|staff|support).{0,20}(off|cancel|not needed|not required|nahi chahiye)"
    r"|\bi('?m| am) (fine|okay|ok|alright|safe|good|better)\b|\bfalse alarm\b|\bnot an emergency\b|\bit'?s nothing\b|\bno emergency\b|\bjust (kidding|joking)\b"
    r"|\bi (don'?t|do not) (want|need) (staff|anyone|anybody|a person|a human|to (talk|speak|be connected))"
    r"|(staff|support|kisi se|insaan).{0,15}(nahi|nahin|mat)|\bmat (jodo|milao|bulao|karo)\b|\bzaroorat nahi\b|\bkoi zaroorat nahi\b|\bwapas (baat|aao)\b|\brehne do\b"
    r"|(स्टाफ|इंसान|किसी|सपोर्ट).{0,25}(नहीं चाहिए|मत|ज़रूरत नहीं|जरूरत नहीं|नहीं करनी|नहीं करना)|कॉल मत|जोड़ो मत|जोड़ना मत|रहने दो|रहने दीजिए|कोई जरूरत नहीं|कोई ज़रूरत नहीं|मैं ठीक हूं|मैं ठीक हूँ|सब ठीक है"
    r"|(اسٹاف|کسی سے).{0,20}(نہیں|مت)|ضرورت نہیں|رہنے دو|میں ٹھیک ہوں"
    r"|^(no|nope|no thanks|no thank you|nahi|nahin|नहीं|नही|نہیں)( thanks| thank you)?$"
)


def wants_cancel_handover(norm: str) -> bool:
    return bool(_CANCEL_HANDOVER.search(norm))
