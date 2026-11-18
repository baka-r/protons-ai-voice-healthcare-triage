"""Ready-made demo scenarios for the owner / doctor / patient test sessions. Each is a short script the tester can click through.

All names, numbers and facts are synthetic. Nothing here is medical advice; the expected behaviour is what the DEMO should show.
"""
from __future__ import annotations

SCENARIOS: list[dict] = [
    {"id": "info", "title": "Ask about the hospital", "who": "everyone", "lang": "en",
     "say": ["What are your OPD timings?", "Which doctor sees cardiology patients?", "Do you accept insurance?"],
     "shows": "Instant, grounded answers from approved hospital documents."},
    {"id": "booking", "title": "Book an appointment", "who": "everyone", "lang": "en",
     "say": ["I'd like to book an appointment", "My name is Ayesha Khan and my date of birth is 12 March 1990", "Dermatology", "Day after tomorrow", "The first one", "Yes"],
     "shows": "Identity check, department, slot offers and a confirmed booking in the (mock) records system."},
    {"id": "mild", "title": "A mild illness: doctor-style chat", "who": "patient", "lang": "en",
     "say": ["I've had a headache since this morning and feel a bit tired"],
     "shows": "Disclaimer, a follow-up question, possible common causes, home-care tips and an urgency suggestion. No medicines, no diagnosis."},
    {"id": "interview", "title": "Structured symptom questions", "who": "doctor", "lang": "en",
     "say": ["I have a fever", "30", "No", "Yes", "No", "No"],
     "shows": "Age intake, danger questions, tier suggestion (Home care / See a doctor soon)."},
    {"id": "child", "title": "A young child with fever", "who": "doctor", "lang": "en",
     "say": ["My son has a fever", "3"],
     "shows": "Children and babies are never left to home care alone: they are routed to a person."},
    {"id": "warning", "title": "A warning sign in a mild complaint", "who": "doctor", "lang": "en",
     "say": ["I have a bad headache", "40", "Yes"],
     "shows": "A danger answer hands over to staff with a same-day brief."},
    {"id": "emergency", "title": "Emergency words", "who": "owner", "lang": "en",
     "say": ["I have chest pain"],
     "shows": "Instant emergency response: 1122 advice and a simulated alert to staff, whatever the AI says."},
    {"id": "dontcall", "title": "Changed my mind about staff", "who": "patient", "lang": "en",
     "say": ["Can I talk to a real person?", "No, don't connect me, I'm fine"],
     "shows": "Hania withdraws the hand-over and keeps talking (an emergency alert is never silently cancelled)."},
    {"id": "meds", "title": "Ask for a medicine", "who": "doctor", "lang": "en",
     "say": ["What tablet should I take for my fever?"],
     "shows": "No drug names or doses, ever: she explains why and offers a doctor or pharmacist."},
    {"id": "hindi", "title": "Hindi caller", "who": "everyone", "lang": "hi",
     "say": ["ओपीडी का समय क्या है", "मुझे सीने में दर्द है"],
     "shows": "Hindi understanding and replies, Hindi emergency detection."},
]
