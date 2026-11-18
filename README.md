# Hania — hospital voice assistant (MVP demo)

A calm voice assistant for a hospital. Hania books, changes and cancels appointments, answers hospital questions from approved
documents, and talks through common health concerns **like a caring doctor would** — asking follow-up questions, looking up
MedlinePlus, and explaining what something *could* be. She always says she is an **AI testing agent, not a professional doctor**.
She connects the caller to a human **only** for emergencies, distress, or when the caller asks. The hand-over is **simulated**
(a staff web page shows the incoming call; no real telephony).

> **Demo only. Synthetic data only. Not clinically approved.** Red-flag rules, scripts and the doctor-mode prompt are drafts that a
> clinician must review before any real use.

Live demo: https://protons.upscaleleads.cloud  ·  staff console: `/staff`

## Run it locally (Docker only)

```bash
cp .env.example .env     # add your keys
docker compose up -d --build
```

| URL | What |
|---|---|
| http://localhost:8080 | Call screen (allow the microphone; or use the keyboard button to type) |
| http://localhost:8080/staff | Staff console (PIN from `.env`) |
| http://localhost:8000/api/health | Liveness |

First start downloads the voice image (~5 GB) and models. Use headphones for the cleanest demo.
Secrets live in `.env` (gitignored). **Rotate any key that was ever pasted into a chat or committed.**

## What Hania does

| Say | What happens |
|---|---|
| "I'm feeling sick, I'm vomiting, what should I do?" | Disclaimer, a follow-up question or two, then possible common explanations, self-care and warning signs (no medicines/doses) |
| "I'd like to book an appointment" → name **Ayesha Khan**, DOB **12 March 1990** → department → date → time → yes | Verified against the mock EMR, booked |
| "What are the visiting hours?" | Spoken verbatim from **approved** documents |
| "I have chest pain" / "I can't breathe" | Emergency path: tells the caller to call 1122 and alerts staff |
| "Can I talk to a person?" or the link below the controls | Simulated hand-over; open `/staff` and press **Accept** |

Synthetic identities: Ayesha Khan 1990-03-12, Hamza Ali 1985-07-21, Fatima Noor 2001-11-05, Usman Raza 1978-01-30, Sara Malik 1995-09-18.

## Safety design

1. **Red-flag rules run first on every utterance** (English, Urdu script, Roman Urdu). A hit means emergency hand-over; the AI can never cancel it.
2. **A second AI check runs in parallel** and can only *add* caution (interrupting an already-given reply if needed).
3. **Doctor mode limits are enforced in code**, not just in the prompt: possible explanations only (never "you have X"), no medicine names or doses,
   an output guard rejects any reply that breaks this, and anything uncertain falls back to a fixed interview or staff. Babies, children and pregnancy get extra caution.
4. **Allow-listed actions:** appointments, approved hospital information, general health conversation, hand-over.
5. **Fail closed:** unclear speech twice, 3 failed ID checks, AI outage while symptoms are mentioned, any exception → a human.
6. **Privacy:** identity details are parsed locally and never sent to the cloud LLM; stored transcripts and staff views are PII-masked; only symptom words go to MedlinePlus.
7. **Security:** HMAC staff tokens + login lockout, cross-origin websocket rejection, rate limits and per-IP caps, hardened non-root containers,
   CSP and security headers, hash-chained audit log, production start-up refuses weak secrets.

## Architecture

```
Browser (React + Chakra + Motion, Silero VAD in-browser) --WebSocket--> nginx --> agent (FastAPI)
   agent: STT (Groq key pool -> OpenAI -> local whisper)  ->  safety rules  ->  dialog engine
          LLM (OpenAI -> Groq key pool: classifier, doctor mode)  |  MedlinePlus / Wikipedia lookup
          mock EMR (FHIR-style) | ChromaDB + fastembed (approved docs) | PostgreSQL (ERD, audit)
          TTS: Kokoro-82M female voice (local), fixed lines + booking phrases pre-rendered
```

## Evidence (from this repo)

* 334 unit tests; a ~1,200-case synthetic safety regression (emergency/distress/abuse recall 100%, 0 leaks, 0 false escalations, 12/12 multi-turn scenarios).
* Live e2e suite (security, persona, doctor mode, booking, concurrency, audit) and a latency benchmark: rule-answered turns ~10–80 ms server time,
  voice turns ~300–900 ms from end of speech to first audio (excludes the ~380 ms end-of-speech wait in the browser).
* These are regression/engineering evidence, **not** clinical validation.

## Testing with patients, QA, doctors and the owner

* [docs/PILOT_PLAN.md](docs/PILOT_PLAN.md): roles, consent, weekly rhythm, stop rule, success measures (written for Pakistan).
* [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md): a 10-minute script; the same scenarios are clickable inside the app (Details → "Try these").
* [docs/CLINICAL_REVIEW.md](docs/CLINICAL_REVIEW.md): the checklist doctors sign before real patients use it.
* `/staff`: hand-overs (with a clinical brief), **Doctor review** (mark answers safe / wrong / unsafe, export corrections as test cases),
  **Owner** dashboard (calls, urgency mix, feedback, speed, AI health) and **Accounts** (per-person logins; the owner is `owner`).
* `docker compose exec agent python -m app.triage_eval`: safety gates (emergency recall 100%, no under-triage, medicine requests blocked).

## Operate

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): production overlay, shared-proxy or standalone Caddy, backups, monitoring, rotation.

```bash
docker run --rm protons-triage-agent python -m pytest -q          # after: docker compose build agent
docker compose exec -T agent python - < scripts/e2e_live.py        # live end-to-end
docker compose exec -T agent python - < scripts/bench_latency.py   # latency
docker compose exec -T agent python - < scripts/e2e_clinic.py      # accounts, roles, tiers, feedback, doctor review, owner stats
docker compose exec -T agent python - < scripts/bench_gaps.py      # audible gaps in streamed speech
docker compose exec agent python -m app.seed_db                    # seed synthetic data
```

## Known limits

* English voice only; Urdu callers are handed to staff (no suitably licensed free Urdu voice).
* Speech and text go to cloud STT/LLM providers (Groq/OpenAI): use synthetic data and team voices only, or set `STT_ROUTE_ORDER=local`.
* Mock EMR, shared demo staff PIN, no SSO; schema via `create_all` (no migrations yet); one agent process holds live-call state in memory.
