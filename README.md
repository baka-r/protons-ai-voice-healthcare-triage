# Aria — hospital voice assistant (MVP demo)

A Jarvis-style voice assistant for a hospital. It answers appointment and hospital-information
calls, **never diagnoses or advises on medicine**, and hands the call to a human when it is unsure
or when anything looks like an emergency. The hand-over is **simulated**: a staff web page shows the
incoming call; no real telephony is involved.

> **Demo only. Synthetic data only. Not clinically approved.** The red-flag list and spoken scripts are
> drafts that a clinician must review before any real use.

## Run it (Docker only)

```bash
docker compose up -d --build
```

| URL | What |
|---|---|
| http://localhost:8080 | The call screen (press **Begin call**, allow the microphone) |
| http://localhost:8080/staff | Staff console (PIN from `.env`, default `1234`) |
| http://localhost:8000/api/health | Component health |

First start downloads the Kokoro voice image and models (a few minutes). Use headphones for the
best demo (echo cancellation works, but a headset is cleaner).

Secrets live in `.env` (gitignored; copy `.env.example`). Only the `agent` container receives API keys;
the browser never sees them. **Rotate any key that has been pasted into a chat or committed anywhere.**

## Try these

| Say | What happens |
|---|---|
| "I'd like to book an appointment" → name **Ayesha Khan**, DOB **12 March 1990** → "cardiology" → "tomorrow" → pick a time → "yes" | Verified against the mock EMR, booked |
| "Cancel my appointment" / "Reschedule my appointment" | Finds Ayesha's seeded Cardiology visit |
| "What are your OPD timings?" / "Is there parking?" | Spoken verbatim from **approved** documents only |
| "I have chest pain" | Emergency path: stops normal replies, alerts staff, tells the caller to call 1122 |
| "What medicine should I take for a fever?" | Refused (no medical advice) and handed to staff |
| "Can I talk to a person?" or the **Talk to a person** button | Simulated hand-over; open `/staff` and press **Accept** |
| Keep a typed fallback: **Type** button | Same pipeline without the microphone |

Demo identities (synthetic): Ayesha Khan 1990-03-12, Hamza Ali 1985-07-21, Fatima Noor 2001-11-05,
Usman Raza 1978-01-30, Sara Malik 1995-09-18.

## How it stays safe

1. **Red-flag rules run first on every utterance** (English, Urdu script, Roman Urdu). Hit → emergency hand-over.
2. **The AI can only add caution.** A second LLM check runs in parallel; if it flags something the call goes to a human. It can never cancel a rule hit.
3. **The AI never writes what the caller hears.** Replies are fixed scripts, templates, or approved document text.
4. **Allow-listed intents only:** appointments, hospital info, "a person". Everything else → refuse + offer staff.
5. **Output guard:** dynamic text containing dosage, drug or diagnosis language is replaced by a hand-over.
6. **Fail closed:** low speech confidence twice, 3 failed ID checks, LLM timeout, any exception → human.
7. **Identity details are parsed locally** and never sent to the cloud LLM; stored utterances are PII-masked.
8. **Only approved, current, latest-version documents** are ever embedded. Drafts, superseded and expired ones are recorded but excluded.
9. **Audit log** is append-only and hash-chained (`GET /api/audit/verify` with the staff PIN header).

## Architecture

```
Browser (Chakra UI + Motion + three.js HUD, Silero VAD in-browser)
   │  WebSocket: 16 kHz PCM up, 24 kHz PCM down
   ▼
agent (FastAPI) ── STT (OpenAI/Groq/local) ── safety rules ── LLM classifier (gpt-6-luna, effort=low)
   │                                            │                 └─ strict JSON, can only add caution
   │                                            ├─ mock-emr (FHIR-style, synthetic)
   │                                            ├─ ChromaDB + fastembed (approved docs only)
   │                                            └─ PostgreSQL (ERD: sessions, utterances, escalations, audit…)
   └─ TTS ── tts (Kokoro-82M, female voice af_heart, local)
```

## Latency design

Browser-side VAD ends a turn quickly; fixed lines (greeting, refusals, hand-over) are **pre-rendered**
and play instantly; dynamic replies are synthesised **sentence by sentence**; speaking stops the moment
you talk (barge-in); the LLM runs at `reasoning effort = low`; a "one moment" filler plays if a turn
exceeds ~0.9 s. The HUD shows live per-turn timings. Measure on your machine — CPU-only TTS is the
main variable.

## Configuration (`.env`)

See `.env.example`. Useful switches: `LLM_PROVIDER=openai|groq`, `LLM_MODEL`, `LLM_REASONING_EFFORT`
(keep `none`/`low` for speed; `high` is used only for staff hand-over summaries), `STT_PROVIDER=openai|groq|local`,
`TTS_VOICE`, `TTS_SPEED`.

Optional: free offline speech-to-text — `docker compose build --build-arg WITH_LOCAL_STT=1 agent`, then
`STT_PROVIDER=local` (slower on CPU). NVIDIA GPU for the voice: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`.
HTTPS for phone demos: `docker compose --profile https up -d` then open `https://<your-pc-ip>:8443`.

## Tests

```bash
docker compose build agent
docker run --rm protons-triage-agent python -m pytest -q
```

Covers red-flag recall/precision on a synthetic English/Urdu/Roman-Urdu corpus, the output guard, document
approval rules, the audit hash chain, and the dialog engine flows (with fake LLM/EMR/RAG).

## Known limits

- English voice only. Urdu callers are understood well enough to be handed to staff, but there is no free Urdu voice with a clean licence (MMS-TTS is non-commercial).
- Speech goes to a cloud STT provider by default; use synthetic data and team voices only. Switch to `STT_PROVIDER=local` to stay on-machine.
- The mock EMR is FHIR-*style*, not a full FHIR R4 server. Staff console auth is a shared demo PIN.
- Schema is created with `create_all` (no Alembic migrations yet). Concurrency tested lightly.
