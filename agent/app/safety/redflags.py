"""Deterministic red-flag detector (English, Urdu script, Roman Urdu).

DRAFT - NOT CLINICALLY APPROVED. Every pattern here must be reviewed and signed off
by a clinician before any real use. The detector is intentionally biased towards
over-triage: a false alarm only hands the call to a human, a miss can harm someone.

It runs on EVERY caller utterance before anything else. The LLM can only add caution
on top of this; it can never cancel a hit from this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.safety.text import normalize

# kind: "emergency" (medical/physical danger) | "self_harm" | "abuse"
_RAW: list[tuple[str, str, str]] = [
    # ---------------- English: cardiac / breathing ----------------
    ("cardiac", "emergency", r"chest (pain|pains|tightness|pressure|heaviness|discomfort|hurts|is hurting|aches|burns)|chest (feels|feel|is|has been) (very |so )?(tight|heavy|crushed|burning)|pain in (my |the )?chest|heart attack|crushing (pain|chest)|pain.{0,25}left arm|heart (is )?(racing|pounding|stopped)"),
    ("breathing", "emergency", r"(can'?t|cannot|unable to|struggling to|hard to|difficulty|trouble|difficult) (to )?(breathe|breath|breathing)|can'?t (catch|get) (my |any |enough )?(breath|air)|short(ness)? of breath|(isn'?t|aren'?t|wasn'?t|is not|are not|not|stopped|stops|barely|hardly|won'?t|can'?t) breathing|gasping|choking|(turning|turned|going|gone|went) blue|blue lips|breathless|no breath"),
    # ---------------- neuro ----------------
    ("neuro", "emergency", r"\bstroke\b|face (is )?drooping|slurred speech|can'?t speak|sudden (weakness|numbness|confusion)|seizure|convuls\w*|\bfitting\b|unconscious|passed out|fainted|collapsed|unresponsive|(isn'?t|is not|aren'?t|not|stopped|won'?t|wouldn'?t) (responding|moving|waking( up)?|conscious|answering|reacting)|won'?t wake|paraly\w*|can'?t move (my )?(arm|leg|face|side)|worst headache"),
    # ---------------- bleeding ----------------
    ("bleeding", "emergency", r"heavy(ly)? bleeding|bleeding (a lot|heavily|badly|profusely)|(won'?t|will not|not) stop bleeding|bleeding (that )?(won'?t|will not) stop|lots? of blood|coughing (up )?blood|vomiting blood|vomit(ing)? (is )?(red|black)|blood in (my )?(vomit|stool)|black stool|bleeding .{0,15}(won'?t|not) stop"),
    # ---------------- pregnancy ----------------
    ("pregnancy", "emergency", r"(pregnan\w*|labou?r|contractions?).{0,40}(bleed\w*|severe pain|early|not moving|stopped moving)|baby (is )?(not|stopped) moving|in labou?r|(my )?waters? broke"),
    # ---------------- poison / overdose ----------------
    ("poison", "emergency", r"overdos\w*|took too many (pills|tablets)|swallowed (a |some |the )?(poison|bleach|pills|battery|coin|magnet|something)|poison\w*|drank (bleach|acid|kerosene)"),
    # ---------------- allergy ----------------
    ("allergy", "emergency", r"anaphyla\w*|throat (is )?(closing|swelling|tight)|swelling (of )?(my )?(face|lips|tongue|throat)|allergic reaction.{0,30}(breath|swell)"),
    # ---------------- trauma ----------------
    ("trauma", "emergency", r"(car|road|bike|motorcycle|traffic) (accident|crash)|(had|got in|been in|was in) an accident|broken (bone|leg|arm|neck|back)|(leg|arm|neck|back|bone|hip) (is |looks |seems )?broken|hit (my|his|her|their) head.{0,40}(vomit|confus|dizzy|unconscious|bleed)|bone (sticking|poking)|severe burn\w*|burned badly|head injury|fell from|electric shock|drowning|drowned|got shot|been shot|was shot|gunshot|stabbed"),
    # ---------------- infant / child ----------------
    ("infant", "emergency", r"(baby|infant|newborn|child|toddler|kid|son|daughter).{0,30}(not breathing|stopped breathing|turning blue|limp|unresponsive|won'?t wake|seizure|convuls\w*)"),
    # ---------------- diabetic ----------------
    ("diabetic", "emergency", r"(sugar|glucose).{0,20}(very low|dangerously|too low|too high)|diabetic.{0,20}(unconscious|confused|collapse\w*)"),
    # ---------------- severe pain / generic distress ----------------
    ("severe_pain", "emergency", r"severe pain|unbearable pain|excruciating|worst pain|can'?t (take|bear|stand) (the|this) pain"),
    ("generic", "emergency", r"\bambulance\b|\bdying\b|going to die|life.?threatening|call (an )?(ambulance|911|1122|115)|need help (now|urgently|immediately|right now)|\b(somebody|someone|anybody|anyone) (please )?help\b|please help me$|^help me$|^help$|\bit'?s an emergency\b|\bthis is an emergency\b|\bmedical emergency\b|\bhave an emergency\b|\bthere'?s an emergency\b|^(an )?emergency$|\bemergency (hai|hogayi|ho gayi|hogai|hogaya|ho gaya)\b"),
    # ---------------- self harm ----------------
    ("self_harm", "self_harm", r"suicid\w*|kill (myself|my self)|end(ing)? (my|this) life|want to die|wanna die|don'?t want to (live|be alive)|hurt(ing)? myself|harm(ing)? myself|self.?harm|better off (dead|without me)|no reason to live|take my own life"),
    # ---------------- abuse / violence ----------------
    ("abuse", "abuse", r"\b(he|she|they|partner|husband|wife|boyfriend|girlfriend|father|mother|dad|mum|mom|parents?|boss|uncle|brother|stepfather) (hits?|beats?|hurts?|threatens?|abuses?|attacks?|slaps?|chokes?|assaults?|is hurting|is beating) me\b|being (abused|beaten|attacked|hit)|someone (is )?(hurting|attacking|beating) me|domestic violence|\braped\b|sexual assault|i'?m in danger|i am in danger|i feel unsafe|not safe at home"),
    # ---------------- Urdu script ----------------
    ("cardiac", "emergency", r"سینے (میں|کا|کی) (درد|جکڑن|دباو|دباؤ)|دل کا دورہ|ہارٹ اٹیک|دل بند|دل کی دھڑکن (تیز|رک)"),
    ("breathing", "emergency", r"سانس (نہیں|نہ|لینے میں|پھول|رک|بند|اکھڑ)|دم (گھٹ|نہیں)|گلا بند"),
    ("neuro", "emergency", r"بے ?ہوش|ہوش (میں )?نہیں|دورہ (پڑ|پر)|مرگی|جھٹکے|فالج|چہرہ (ٹیڑھا|ٹیڑھی)|زبان لڑکھڑا"),
    ("bleeding", "emergency", r"خون (بہہ|بہ |بہت|نہیں رک|آ رہا|آرہا|کی الٹی|کی قے)|الٹی (میں )?خون|خون والی"),
    ("self_harm", "self_harm", r"خودکشی|خود کشی|مرنا چاہ|مر جانا چاہ|جینا نہیں چاہ|جان لے (لوں|لوں گا|لوں گی)|خود کو (نقصان|مار|زخمی)"),
    ("poison", "emergency", r"زہر|زیادہ گولیاں|اوور ?ڈوز"),
    ("trauma", "emergency", r"حادثہ|ایکسیڈنٹ|ہڈی ٹوٹ|جل گ(یا|ئی|ئے)"),
    ("generic", "emergency", r"ایمرجنسی|ایمبولینس|جان بچاؤ|جان بچاو|مدد کرو|بچاؤ|مر رہا|مر رہی|مرنے والا|مرنے والی"),
    ("infant", "emergency", r"(بچہ|بچی|بچے).{0,25}(سانس نہیں|بے ?ہوش|نیلا|نیلی|ہل نہیں)"),
    ("severe_pain", "emergency", r"شدید درد|برداشت سے باہر|درد برداشت نہیں"),
    ("pregnancy", "emergency", r"(حمل|حاملہ).{0,30}خون"),
    ("allergy", "emergency", r"الرجی.{0,25}(سانس|سوجن)|گلے (میں )?سوجن"),
    # ---------------- Roman Urdu ----------------
    ("cardiac", "emergency", r"(sin[ae]?|seen[ae]?|chest|dil) (mein|men|mei|me|ka|ki) ?(shadeed |bohat |bahut |zyada )?(dard|jakran|bhari ?pan|dabao)|(dil ka|heart) (daura|attack)|dil band|dil ki dhadkan (tez|ruk)"),
    ("breathing", "emergency", r"(saans|sans|dam)\s*(nahi|nahin|nai|nhi|lene (m\w+|ki) (mushkil|takleef|dikkat)|phool|ruk|band|ukhad)|saans (lene )?(m\w+ )?(dikkat|mushkil|takleef)|gala band|dam (ghut|ghat)\w*"),
    ("neuro", "emergency", r"\b(behosh|bayhosh|be hosh)\b|hosh (m\w+ )?nahi|daura (par|pad)|mirgi|jhatke|\bfits?\b|falij|faalij|chehra (tehra|terha)|zuban (larkhara|lakhra)"),
    ("bleeding", "emergency", r"khoon (beh|bah|nahi ruk|nahin ruk|bohat|bahut|aa raha|aa rahi|ki ulti)|ulti (m\w+ )?khoon|khoon wali ulti|khoon nahi ruk"),
    ("self_harm", "self_harm", r"khud ?kushi|khud kushi|marna hai|mar ja+na hai|marna chah\w*|mar jaana chah\w*|mar jana chah\w*|jeena nahi chah\w*|jina nahi chah\w*|apni jaan le|khud ko (nuksan|maar|hurt)"),
    ("poison", "emergency", r"\bzeher\b|\bzehar\b|\bzahar\b|zyada goli\w*|zyadah goli\w*"),
    ("trauma", "emergency", r"\bhadsa\b|\bhaadsa\b|haddi toot|jal gay\w*|jal gaya|jal gayi"),
    ("generic", "emergency", r"jaan bachao|jan bachao|madad karo|\bbachao\b|mar raha|mar rahi|mar rha|mar jaunga|mar jaungi|marne wala|marne wali"),
    ("infant", "emergency", r"(bacha|bachi|bachay|bache|baby).{0,25}(saans nahi|saans nahin|behosh|neela|neeli|hil nahi)"),
    ("severe_pain", "emergency", r"shadeed dard|bohat (zyada|zyadah) dard|bardasht se bahar|dard bardasht nahi|bohat shadeed"),
    ("pregnancy", "emergency", r"(hamal|pregnant|hamla|hamlah).{0,30}khoon"),
    # ---------------- Hindi (Devanagari) - normalised text has no nukta
    ("cardiac", "emergency", r"सीने (में|का|की) (तेज )?(दर्द|जकड़न|दबाव|भारीपन|जलन)|सीने में दर्द|दिल का दौरा|हार्ट अटैक|हार्ट अटैक|दिल (बैठ|रुक|की धड़कन (रुक|तेज))|छाती में (दर्द|जकड़न)"),
    ("breathing", "emergency", r"सा[ंँ]स (नहीं|न|लेने में|फूल|रुक|बंद|उखड़|नहीं आ)|दम (घुट|नहीं)|गला (बंद|घुट)|सांस की (तकलीफ|दिक्कत)|साँस की (तकलीफ|दिक्कत)"),
    ("neuro", "emergency", r"बेहोश|होश में नहीं|होश नहीं|दौरा (पड़|पड)|मिर्गी|लकवा|फालिज|चेहरा टेढ़ा|जबान लड़खड़ा|बोल नहीं पा|आंखें पलट|आँखें पलट"),
    ("bleeding", "emergency", r"खून (बह|बहुत|नहीं रुक|आ रहा|आ रही|की उल्टी|की कै)|(उल्टी|कै|पाखाने|मल) (में )?खून|खून रुक नहीं|खून नहीं रुक"),
    ("self_harm", "self_harm", r"आत्महत्या|खुदकुशी|खुद ?कुशी|मरना चाहत|मर जाना चाहत|जीना नहीं चाहत|जान दे(ना| दूं| दूँ| दूंगी| दूँगी)|खुद को (नुकसान|मार|चोट|खत्म)|अपनी जान ले"),
    ("poison", "emergency", r"जहर|विष (पी|खा)|ओवरडोज|ज्यादा गोलियां|ज्यादा गोलियाँ|फिनाइल पी|कीटनाशक"),
    ("trauma", "emergency", r"एक्सीडेंट|हादसा|दुर्घटना|हड्डी टूट|जल गय|करंट लग|गोली लग|चाकू (लग|मार)|सिर में चोट"),
    ("generic", "emergency", r"इमरजेंसी|आपातकाल|एम्बुलेंस|एंबुलेंस|जान बचाओ|बचाओ|मदद करो|मर रहा|मर रही|मरने वाला|मरने वाली"),
    ("infant", "emergency", r"(बच्चा|बच्ची|बच्चे|बेटा|बेटी|शिशु).{0,25}(सा[ंँ]स नहीं|बेहोश|नीला|नीली|हिल नहीं|दौरा|उठ नहीं)"),
    ("severe_pain", "emergency", r"बहुत (तेज|ज्यादा) दर्द|असहनीय दर्द|दर्द बर्दाश्त नहीं|भयानक दर्द|शदीद दर्द"),
    ("pregnancy", "emergency", r"(गर्भ|प्रेग्नेंट|गर्भवती|हामिला).{0,30}खून"),
    ("allergy", "emergency", r"एलर्जी.{0,25}(सा[ंँ]स|सूजन)|गले में सूजन|चेहरे पर सूजन"),
]

# "emergency department hours" is an information question, not an emergency.
_EMERGENCY_INFO = re.compile(
    r"\b(accident and emergency|emergency) (room|department|dept|ward|services?|unit|care|timings?|hours|number|contact|entrance|section|wing)\b|\ber timings?\b"
    # informational questions about the ambulance SERVICE are not a request for one ("send an ambulance" still escalates)
    r"|\b(do you have|have you got|is there|are there|got) (an? |any )?ambulances?( service| services| facility| available)?\b(?! (to|for|at|now|here|outside|coming|please))"
    r"|\bambulances? (service|services|facility|number|charges|cost|fee|fees|timings?|available|availability|contact)\b"
)

_COMPILED = [(cat, kind, re.compile(pat)) for cat, kind, pat in _RAW]


@dataclass(frozen=True)
class RedFlag:
    category: str
    kind: str  # emergency | self_harm | abuse
    matched: str


def scan_red_flags(text: str) -> RedFlag | None:
    norm = normalize(text)
    if not norm:
        return None
    scrubbed = _EMERGENCY_INFO.sub(" emergencyinfo ", norm)
    for cat, kind, rx in _COMPILED:
        m = rx.search(scrubbed)
        if m:
            return RedFlag(category=cat, kind=kind, matched=m.group(0)[:60])
    return None
