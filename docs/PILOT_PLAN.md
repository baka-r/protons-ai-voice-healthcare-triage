# Pilot plan: patients, QA testers, doctors and the owner (Pakistan)

Hania is a **testing agent, not a doctor**. This plan describes how to test it safely with real people while the content is still unreviewed. Read it together with [CLINICAL_REVIEW.md](CLINICAL_REVIEW.md).

## 1. Who does what

| Group | What they do | Where |
|---|---|---|
| **Patients** (small invited group) | Talk to Hania about ordinary things: opening hours, booking, a mild health question. Tap 👍/👎 on answers. Do not share real personal or medical details. | `https://protons.upscaleleads.cloud` |
| **QA testers** | Work through the scripted scenarios (Details → "Try these"), then try to break her: odd wording, Hindi/Urdu/Roman Urdu, interruptions, silence. Report with 👎 + a one-line comment. | same page |
| **Doctors** | Review flagged calls in **Staff → Doctor review**: mark each Hania answer *Safe*, *Wrong* or *Unsafe*, give the correct urgency and wording. Weekly 60-minute session. | `/staff` with their own account |
| **Owner** | Watches **Staff → Owner** (calls, hand-over rate, urgency mix, feedback, speed, AI health). Decides go / pause. | `/staff` with the owner account |

Accounts: the owner signs in as `owner` (password = the server's `OWNER_PASSWORD`, or `STAFF_PIN` if that is unset) and creates each doctor under **Staff → Accounts**. Change the owner password after the first sign-in. The shared desk PIN only opens the hand-over queue.

## 2. Before anyone outside the team tests
- [ ] A doctor has read the red-flag list and the 18 symptom topics (`docs/CLINICAL_REVIEW.md`) and signed the first page. **Do not invite patients before this.**
- [ ] `python -m app.triage_eval` passes (emergency recall 100%, no under-triage, medicine requests blocked).
- [ ] The three Groq keys and the OpenAI key have been **rotated** (they were shared in plain text during development).
- [ ] Consent wording below is approved by whoever is responsible for compliance.
- [ ] A named person watches the staff console during each test session (hand-overs are simulated, nobody is actually called).

## 3. Consent and privacy (draft wording, shown on the start screen)
"I understand Hania is an AI testing agent, not a doctor, and that this is a test: my conversation (with names, phone numbers and ID numbers masked) is stored for quality review by hospital staff and doctors. In an emergency I will call 1122."

- Names, phone numbers, CNIC and e-mail are masked before anything is stored or shown to staff.
- Transcripts and feedback text are deleted automatically after `RETENTION_DAYS` (default 30). Doctor verdicts and counts are kept.
- Doctors and the owner see only masked transcripts. Every transcript view is written to the tamper-evident audit log.
- Pakistan: confirm with counsel how the PMDC rules on tele-advice, the Personal Data Protection Bill (still draft at the time of writing) and any provincial health-care-commission rules apply before testing with real patients. This document is not legal advice.

## 4. Weekly rhythm
1. **Mon**: QA runs the scripted scenarios and a fresh round of free-form tests.
2. **Wed**: doctors review flagged calls (default view: *Needs attention*): thumbs-down, same-day/emergency tier, hand-overs. Wrong/unsafe verdicts need a correction.
3. **Thu**: engineering exports corrections (**Doctor review → Export corrections**), adds them to `agent/seed/triage_scenarios.json`, fixes, re-runs `python -m app.triage_eval` and the e2e scripts.
4. **Fri**: owner reviews the dashboard with the doctors and decides: continue, widen, or pause.

## 5. Stop rule
Pause the pilot immediately (turn off the site or the doctor-mode setting) if **any** of these happens:
- a doctor marks an answer **Unsafe**;
- an emergency phrase is not escalated;
- Hania names a medicine or dose, or gives a definite diagnosis;
- a transcript shows an unmasked personal identifier.
Resume only after the cause is fixed, a new test case covers it, and a doctor has re-checked it.

## 6. Success measures (agree numbers with the doctors)
- 100% of scripted emergency phrases escalate (automatic).
- 0 answers marked Unsafe; fewer than __% marked Wrong after the second week.
- Tester thumbs-up rate above __%.
- Typical voice-to-voice time under 2.5 s; fewer than 1 in 20 calls hit the "AI busy" limited mode.
- Hand-over rate stays inside the range the doctors consider reasonable.

## 7. Known limits of the current setup
- **AI model:** free Groq keys. They are rate-limited; under load Hania drops to rule-based answers or hands over (the start screen says "the AI is busy"). Budget for a paid key before more than ~10 concurrent testers.
- **Voice:** a CPU-only voice engine; long answers that are not pre-recorded start about 1-2 s late. Urdu is spoken with a Hindi voice.
- **Hand-over:** simulated. Nobody is rung. Real staff routing needs telephony and an on-call rota.
- **Medical content:** engineer-written and unreviewed until the doctors sign `CLINICAL_REVIEW.md`. Emergency number is Pakistan's **1122**.
- **Data:** the hospital facts, doctors and patients in the demo are synthetic. Replace them with approved real content before any real use.
