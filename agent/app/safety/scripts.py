"""Fixed, reviewable spoken scripts. DRAFT - NOT CLINICALLY APPROVED.

These are pre-rendered to audio at start-up, so they play with ~0 ms TTS delay.
"""
from __future__ import annotations

from app.config import get_settings

_RAW: dict[str, str] = {
    "greeting": (
        "Hi, I'm {name}, the virtual assistant of {hospital}. "
        "I'm an AI testing agent, not a doctor. In an emergency, call {emergency}. "
        "How can I help?"
    ),
    "doctor_disclaimer": "Just so you know, I'm a testing agent and not a professional doctor, so this is general information only.",
    "doctor_outro": "If you're worried or it gets worse, please see a doctor. I can book you an appointment, or connect you to our staff. What would you like?",
    "about_me": (
        "I'm {name}, the virtual assistant of {hospital}. I'm an AI testing agent, not a human and not a professional doctor. "
        "I can talk through how you're feeling and share general health information, help you book, change or cancel an appointment, "
        "and answer questions about the hospital. I can also connect you to our staff whenever you like."
    ),
    "are_you_human": (
        "No, I'm an AI assistant, not a person. If you'd like to speak with a real member of our staff, just say so."
    ),
    "thanks_reply": "You're welcome. Is there anything else I can help you with?",
    "smalltalk": "I'm doing well, thank you for asking. How can I help you today?",
    "capabilities": (
        "I can help you book, change or cancel an appointment, or answer questions about our hospital. "
        "What would you like to do?"
    ),
    "not_caught": "Sorry, I didn't catch that. Could you say it again?",
    "filler": "One moment please.",
    "emergency": (
        "I'm concerned about what you've told me. This may be an emergency. "
        "If you or someone else is in danger, please call {emergency} right now. "
        "I'm connecting you to a member of our staff immediately."
    ),
    "distress": (
        "I'm really sorry you're going through this. You don't have to face it alone. "
        "I'm connecting you to a member of our staff right now. "
        "If you are in immediate danger, please call {emergency}."
    ),
    "medical_refusal": (
        "I'm not able to give medical advice or tell you what's wrong. "
        "A member of our staff can help you with that, so I'm connecting you now."
    ),
    "guidance_intro": (
        "I can't diagnose or recommend medicines, but here is some general guidance from our approved health information."
    ),
    "guidance_outro": (
        "If you're worried, or it gets worse, I can connect you to our staff right now. "
        "Would you like that, or shall I help with an appointment?"
    ),
    "symptom_intro": (
        "I'm sorry you're not feeling well. I can't diagnose you, but I'll ask a few quick yes or no questions "
        "so I can share the right general guidance."
    ),
    "symptom_escalate": (
        "Thank you for telling me. Because of that, I'd like one of our staff to look at this with you, so I'm connecting you now. "
        "If it feels severe or is getting worse, please call {emergency}."
    ),
    "symptom_retry": "Sorry, I need a yes or a no for that one.",
    "symptom_age_q": "First, roughly how old is the person who is unwell?",
    "symptom_age_retry": "A rough age is fine, for example thirty, or six months for a baby.",
    "handover_cancelled": "Okay, no problem. I won't connect you to staff. I'm still here with you. What would you like to talk about?",
    "handover_keep_alert": (
        "I understand, and I'm still here with you. Because of what you told me, I'll keep our team alerted just in case. "
        "Please tell me how you're feeling, and if you're in danger, call {emergency}."
    ),
    "human_request": "Of course. I'm connecting you to a member of our staff now.",
    "handover_wait": "Please stay on the line. A staff member will be with you shortly.",
    "still_waiting": (
        "Thank you for holding. Our staff are still being alerted. "
        "If this is urgent, please call {emergency} now."
    ),
    "connected": "You're now connected with a member of our staff. Please go ahead.",
    "ask_name": "To get started, may I have your full name as registered with the hospital?",
    "ask_dob": "Thank you. And your date of birth, please?",
    "verify_retry": "I couldn't match those details. Let's try once more. Your full name, please?",
    "verify_fail": "I'm unable to verify your details, so I'll connect you to a staff member who can help.",
    "goodbye": "Thank you for calling {hospital}. Take care. Goodbye.",
    "anything_else": "Is there anything else I can help you with?",
    "out_of_scope": (
        "I can help with appointments and hospital information. "
        "Would you like that, or shall I connect you to staff?"
    ),
    "urdu_notice": (
        "I'm sorry, I can currently speak English only. "
        "I'm connecting you to a staff member who can help you further."
    ),
    "degraded": "I'm having a little trouble right now, so I'll connect you to a staff member.",
    "turn_limit": "To make sure you get the right help, I'll connect you to a staff member.",
    "unclear_handover": "I'm sorry, I'm still not understanding. I'll connect you to a staff member.",
    "no_info": (
        "I don't have that information to share. I can connect you to a staff member if you like."
    ),
    "no_appointments": "I couldn't find any upcoming appointments for you. Is there anything else I can do?",
    "never_mind": "No problem. Is there anything else I can help you with?",
    "connected_ui": "",
}


def fixed(key: str) -> str:
    s = get_settings()
    return _RAW[key].format(name=s.assistant_name, hospital=s.hospital_name, emergency=s.emergency_number)


def all_fixed() -> dict[str, str]:
    return {k: fixed(k) for k, v in _RAW.items() if v}
