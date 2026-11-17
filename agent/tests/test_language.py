"""Hindi / Urdu support: text handling, safety rules, intents, localisation, and 'don't call staff' detection."""
import pytest

from app.config import Settings
from app.dialog import rules
from app.safety import scripts
from app.safety.redflags import scan_red_flags
from app.safety.text import normalize
from app.services.lang import HINDI, Localizer, digits_hi
from app.services.stt import norm_lang, script_of


def test_devanagari_words_are_not_split_by_normalisation():
    assert normalize("नहीं!") == "नहीं" and normalize("हाँ, जी") == "हाँ जी"
    assert normalize("ज़हर") == "जहर"  # nukta removed so one spelling matches
    assert rules.is_no(normalize("नहीं")) and rules.is_yes(normalize("हाँ")) and rules.is_yes(normalize("जी हां"))
    assert rules.is_no(normalize("नहीं, खून नहीं है"))


@pytest.mark.parametrize("text", [
    "मुझे सीने में दर्द है", "सांस नहीं आ रही है", "सांस लेने में तकलीफ हो रही है", "वह बेहोश हो गया", "बहुत खून बह रहा है",
    "मैं आत्महत्या करना चाहता हूँ", "उसने ज़हर खा लिया", "एम्बुलेंस बुलाओ", "बच्चा सांस नहीं ले रहा", "मुझे दौरा पड़ा", "दिल का दौरा पड़ा है",
    "मेरी जान बचाओ", "बहुत तेज दर्द है", "गर्भवती है और खून आ रहा है",
])
def test_hindi_red_flags(text):
    assert scan_red_flags(text) is not None, text


@pytest.mark.parametrize("text", [
    "मुझे अपॉइंटमेंट बुक करना है", "ओपीडी का समय क्या है", "पार्किंग कहाँ है", "मेरा नाम आयशा खान है", "धन्यवाद", "मुझे स्टाफ से बात करनी है",
])
def test_hindi_benign_phrases_not_flagged(text):
    assert scan_red_flags(text) is None, text


@pytest.mark.parametrize("text,intent", [
    ("मुझे अपॉइंटमेंट बुक करना है", "book_appointment"), ("मुझे अपॉइंटमेंट रद्द करना है", "cancel_appointment"),
    ("मुझे अपॉइंटमेंट बदलना है", "reschedule_appointment"), ("मुझे स्टाफ से बात करनी है", "talk_to_human"),
    ("धन्यवाद", "thanks"), ("ओपीडी का समय क्या है", "hospital_info"), ("आप कौन हैं", "identity_question"),
    ("क्या आप इंसान हैं", "are_you_human"), ("अलविदा", "goodbye"), ("नमस्ते", "greeting"), ("कौन सी दवा लूँ", "medical_question"),
])
def test_hindi_intents(text, intent):
    assert rules.rule_intent(normalize(text)) == intent


@pytest.mark.parametrize("text", [
    "don't call staff", "I don't want to talk to staff", "no need to connect me", "cancel the call to the staff", "I'm fine", "false alarm",
    "never mind don't transfer me", "no thanks", "no", "staff nahi chahiye", "mujhe kisi se baat nahi karni",
    "स्टाफ से बात नहीं करनी", "कॉल मत करो", "रहने दो", "सब ठीक है", "نہیں",
])
def test_wants_cancel_handover(text):
    assert rules.wants_cancel_handover(normalize(text)), text


@pytest.mark.parametrize("text", [
    "my chest still hurts", "please hurry", "yes connect me", "my mother is not breathing", "how long will it take", "I need help",
])
def test_ordinary_words_do_not_cancel_a_handover(text):
    assert not rules.wants_cancel_handover(normalize(text)), text


def test_language_helpers():
    assert norm_lang("Hindi") == "hi" and norm_lang("Urdu") == "ur" and norm_lang("English") == "en" and norm_lang("hi") == "hi" and norm_lang(None) is None
    assert script_of("मुझे सीने में दर्द है") == "deva" and script_of("مجھے سینے میں درد ہے") == "arab" and script_of("chest pain") is None
    assert digits_hi("1122") == "एक एक दो दो"


def test_hindi_scripts_are_complete_and_formatted():
    loc = Localizer(Settings(data_dir="/tmp/loc"), llm=None)
    english = scripts.all_fixed()
    for key, text in loc.hindi_fixed_lines().items():
        assert "{" not in text and "}" not in text, f"{key} has an unformatted placeholder"
        assert any("ऀ" <= c <= "ॿ" for c in text), key
    # every hand-written line corresponds to a real English script, and the safety-critical ones all exist
    assert set(HINDI) <= set(scripts._RAW)
    for key in ("greeting", "emergency", "distress", "human_request", "handover_wait", "connected", "doctor_disclaimer", "handover_cancelled", "handover_keep_alert"):
        assert key in HINDI, key
    assert loc.fixed("emergency", "hi") and loc.fixed("emergency", "en") is None and "एक एक दो दो" in loc.fixed("emergency", "hi")
    assert "testing" in english["greeting"] and "टेस्टिंग" in loc.fixed("greeting", "hi")


async def test_hindi_booking_flow_with_the_rules_engine():
    from tests.test_engine import mk, A
    from app.dialog.session import Session

    eng, _, _ = mk(A(language="hi", intent="book_appointment"))
    s = Session(id="t", language="hi")
    r = await eng.handle(s, "मुझे अपॉइंटमेंट बुक करना है")
    assert r.handover is None and s.state == "AWAIT_NAME"
    r = await eng.handle(s, "मेरी जान बचाओ")
    assert r.handover and r.handover.urgency == "emergency"


@pytest.mark.parametrize("text", [
    "is there an ambulance", "do you have an ambulance service", "ambulance service number", "is there ambulance available",
])
def test_ambulance_service_questions_are_information_not_emergencies(text):
    assert scan_red_flags(text) is None, text


@pytest.mark.parametrize("text", [
    "send an ambulance", "please send an ambulance", "call an ambulance", "I need an ambulance now", "ambulance please", "is there an ambulance coming",
])
def test_requests_for_an_ambulance_still_escalate(text):
    assert scan_red_flags(text) is not None, text


@pytest.mark.parametrize("text", [
    "which doctor sees cardiology patients", "who is the cardiologist", "which floor is orthopedics on", "do you have an MRI scan",
    "where is the blood bank", "what time is discharge", "do you have wheelchair access", "is there a prayer room",
])
def test_hospital_questions_route_to_info(text):
    assert rules.rule_intent(normalize(text)) == "hospital_info", text


def test_questions_about_hania_stay_persona():
    for t in ("who are you", "what is your name", "are you a robot"):
        assert rules.rule_intent(normalize(t)) in ("identity_question", "are_you_human")


@pytest.mark.parametrize("text", [
    "I wanted to ask about cardiology doctors", "I wanted to ask about consultation fee", "do you have information on blood bank",
    "what is the consultation fee", "I need to know about room types",
])
def test_information_questions_are_not_mistaken_for_booking_or_a_person(text):
    assert rules.rule_intent(normalize(text)) == "hospital_info", text
    assert not rules.mentions_symptoms(normalize(text))


@pytest.mark.parametrize("text,intent", [
    ("I want to talk to a doctor", "talk_to_human"), ("I need a nurse", "talk_to_human"), ("I want to book a consultation", "book_appointment"),
    ("I'd like to make an appointment", "book_appointment"),
])
def test_real_requests_still_work(text, intent):
    assert rules.rule_intent(normalize(text)) == intent, text
