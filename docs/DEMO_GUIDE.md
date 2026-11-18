# Demo guide (10 minutes)

Open `https://protons.upscaleleads.cloud` on a laptop with a microphone (Chrome), and `/staff` on a second screen signed in as the owner.

**Before you start:** Staff → Owner → *Reset demo queue*. Check the start screen shows no "AI is busy" note. Choose how you are testing (Patient / QA tester / Doctor / Owner), tick the consent box, press *Start conversation*.

Open **Details** (top right) → **Try these**: every scenario below is a clickable script that sends each line as if you had spoken it.

| # | Show | Say / click | What the audience should notice |
|---|------|-------------|--------------------------------|
| 1 | Speed + knowledge | "What are your OPD timings?" | Answer in well under a second, from approved hospital documents (Details → *Approved source*). |
| 2 | Booking | Scenario "Book an appointment" | Name + date of birth check, department, slots, confirmation. |
| 3 | Doctor-style chat | "I've had a headache since this morning and I feel tired" | Disclaimer, one follow-up question, "this could be…" explanation, home-care tips, an **urgency chip** (Home care / See a doctor soon). No medicine, no diagnosis. |
| 4 | Structured interview | "I have a fever" → age → yes/no questions | Age intake first, danger questions, tier suggestion. |
| 5 | Young child | "My son has a fever" → "3" | Never left to home care: handed to a person. |
| 6 | Warning sign | "I have a bad headache" → "40" → "Yes" | Hand-over; on the staff screen see the **clinical brief** (urgency, age, the questions and answers). |
| 7 | Emergency | "I have chest pain" | Instant 1122 advice; staff alert with sound; the brief says *Emergency, red flag (rules)*. |
| 8 | Changed my mind | "Can I talk to a real person?" → "No, don't connect me" | Hania withdraws the request and keeps talking. |
| 9 | Medicine | "What tablet should I take for fever?" | She will not name a drug or dose and says why. |
| 10 | Hindi / Urdu | switch the language dropdown, or speak Hindi/Urdu | Detects and answers in the caller's language, emergency detection works in Hindi too. |
| 11 | Feedback | tap 👎 on an answer, add a comment | Appears under **Owner → Latest tester comments** and flags the call in **Doctor review**. |
| 12 | Doctor review | Staff → Doctor review → pick the call → *Wrong* + correction + correct urgency → *Export corrections* | Corrections become test cases; this is how the doctors make her better. |
| 13 | Owner view | Staff → Owner | Calls, hand-over rate, urgency mix, thumbs, speed, AI health. |

## If something goes wrong on stage
- **"The AI is busy"** (free-tier rate limit): fixed questions (hours, booking, emergencies) still work instantly; wait ~1 minute for health chat.
- **No sound:** check the browser's mic/speaker permission; you can always type (keyboard icon).
- **Staff screen empty:** sign out and back in; *Reset demo queue* only hides finished hand-overs.
