"""Red-flag recall/precision on a synthetic corpus. Target: >= 99% recall (Sprint 1 NFR)."""
import pytest

from app.safety.redflags import scan_red_flags

POSITIVE = [
    # English
    "I have chest pain", "my chest feels tight and heavy", "my chest hurts", "I think I'm having a heart attack",
    "I have crushing chest pain going down my left arm", "my heart is pounding and I feel faint",
    "I can't breathe", "he is struggling to breathe", "I am having trouble breathing", "shortness of breath and dizzy",
    "I'm gasping for air", "she is choking on food", "my lips are turning blue", "I can't get any air",
    "my father is unconscious", "she passed out", "my son is having a seizure", "he is having convulsions",
    "I think I'm having a stroke", "his face is drooping", "her speech is slurred speech and she's confused",
    "heavy bleeding that won't stop", "I'm vomiting blood", "I'm bleeding heavily", "there is a lot of blood",
    "I took too many pills", "he swallowed poison", "I overdosed", "he drank bleach", "my daughter swallowed a battery",
    "my baby is not breathing", "my toddler turned blue", "the child is not responding",
    "I want to kill myself", "I don't want to live anymore", "I've been thinking about suicide", "I'm suicidal",
    "I want to hurt myself", "I feel like ending my life",
    "someone is hurting me", "I'm being abused at home", "someone is beating me", "I feel unsafe",
    "I was in a car accident", "I fell from the roof", "he got an electric shock", "I've been stabbed",
    "I have severe burns", "my leg is broken", "he hit his head and is vomiting",
    "I'm having an allergic reaction and my throat is closing", "my face is swelling up after the injection swelling of my face",
    "my wife is pregnant and bleeding heavily", "my baby is not moving",
    "this is an emergency", "please send an ambulance", "I'm dying", "severe pain in my stomach", "unbearable pain",
    "I can't take this pain anymore", "my sugar is dangerously low", "somebody please help", "help",
    # Urdu script
    "مجھے سینے میں درد ہے", "سانس نہیں آ رہی", "میرے والد بے ہوش ہو گئے", "مریض کو دورہ پڑ گیا",
    "بہت خون بہہ رہا ہے", "میں خودکشی کرنا چاہتا ہوں", "اس نے زہر پی لیا", "ایمبولینس بلاؤ",
    "بچہ سانس نہیں لے رہا", "ان کو فالج ہوا ہے", "ایکسیڈنٹ ہو گیا", "دل کا دورہ پڑا ہے", "شدید درد ہے",
    "میری جان بچاؤ", "سانس لینے میں دشواری ہے", "وہ بے ہوش پڑا ہے", "الٹی میں خون آیا", "گلا بند ہو رہا ہے",
    "حمل میں خون آ رہا ہے",
    # Roman Urdu
    "mujhe seene mein dard hai", "meri saans nahi aa rahi", "meri saans phool rahi hai", "sans lene mein dikkat hai",
    "wo behosh ho gaya", "bohat khoon beh raha hai", "ulti mein khoon hai", "main khudkushi karna chahta hoon",
    "usne zeher pi liya", "mere bachay ko saans nahi aa rahi", "dil ka daura pada hai", "hadsa ho gaya",
    "shadeed dard hai", "jaan bachao", "mar raha hoon", "mujhe daura par gaya", "seene mein jakran hai",
    "dil mein dard hai", "chest mein dard hai", "bacha behosh hai", "pregnant hai aur khoon aa raha hai",
    "mujhe marna hai", "emergency hai", "dam ghut raha hai",
]

NEGATIVE = [
    "I'd like to book an appointment with cardiology", "what are your OPD timings",
    "what are the emergency department hours", "is the emergency room open on Sundays", "where is the hospital located",
    "can you help me book an appointment", "please help me book an appointment", "I want to cancel my appointment",
    "do you have parking", "what should I bring to my appointment", "my name is Ayesha Khan",
    "my date of birth is twelfth of March nineteen ninety", "yes please", "tomorrow at ten", "I need to see a skin doctor",
    "what are the visiting hours", "can I reschedule my appointment to next week", "do you take insurance",
    "I want to talk to a person", "thank you goodbye", "good morning", "I'd like to see a heart specialist",
    "I need a flu shot appointment", "I have a headache and want an appointment", "I have knee pain and need an orthopedic appointment",
    "accident and emergency department location", "which departments do you have", "is the pharmacy open at night",
    "mujhe appointment chahiye", "OPD ka time kya hai", "hospital kahan hai", "mera naam ali hai",
    "مجھے اپوائنٹمنٹ چاہیے", "ہسپتال کا وقت کیا ہے",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_positive_phrases_are_flagged(text):
    assert scan_red_flags(text) is not None, f"MISSED red flag: {text!r}"


def test_recall_meets_target():
    hits = sum(1 for t in POSITIVE if scan_red_flags(t))
    assert hits / len(POSITIVE) >= 0.99, f"recall {hits}/{len(POSITIVE)}"


@pytest.mark.parametrize("text", NEGATIVE)
def test_benign_phrases_are_not_flagged(text):
    rf = scan_red_flags(text)
    assert rf is None, f"false alarm on {text!r}: {rf}"


def test_self_harm_kind():
    assert scan_red_flags("I want to kill myself").kind == "self_harm"
    assert scan_red_flags("I have chest pain").kind == "emergency"
    assert scan_red_flags("I'm being abused at home").kind == "abuse"
