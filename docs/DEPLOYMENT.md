# Deploying Hania to a VPS

> Status: **technically deployable, not clinically or legally approved.** Real patient use requires clinician sign-off of the
> red-flag rules and scripts, a privacy/DPIA review, and a hospital-approved identity-verification policy. See "Before real use".

## 1. Server

* Ubuntu 22.04/24.04, **4+ vCPU, 8 GB RAM** (the CPU voice engine uses ~2 vCPU; an NVIDIA GPU makes it much faster via `docker-compose.gpu.yml`).
* Docker Engine + Compose v2. Firewall: allow only 22 (SSH, key-only), 80, 443.
* A DNS `A` record for your domain pointing at the server (needed for automatic HTTPS - microphones require a secure origin).

## 2. Secrets (never commit `.env`)

```bash
cp .env.example .env
openssl rand -hex 32          # -> SECRET_KEY
openssl rand -base64 24       # -> POSTGRES_PASSWORD (12+ chars) and a STAFF_PIN of 8+ characters
```

Set `APP_ENV=prod`. In prod the agent **refuses to start** with a weak `STAFF_PIN`, a default/short `POSTGRES_PASSWORD`, or a missing `SECRET_KEY`.
Put provider keys in `.env` only (`GROQ_API_KEYS=k1,k2,k3`, `OPENAI_API_KEY`). Rotate any key that has ever been pasted into a chat, ticket or screenshot.

## 3. Start

```bash
DOMAIN=hania.example.com docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile backup up -d --build
docker compose ps                      # everything healthy
curl -s https://hania.example.com/api/status
```

First start downloads the voice image and models and pre-renders ~160 spoken phrases (a few minutes; cached on the `agent-data` volume afterwards).

Seed reproducible synthetic demo data (staff user, patients, eval cases, knowledge records):

```bash
docker compose exec agent python -m app.seed_db
```

## 4. Health, logs, monitoring

| Check | How |
|---|---|
| Liveness | `GET /api/health` -> `{"ok":true}` (container healthcheck uses it) |
| Readiness (DB + EMR) | `GET /api/ready` -> 200/503 |
| Public status (booleans only) | `GET /api/status` |
| Provider/key routes, cache sizes | `GET /api/admin/health` (staff token) |
| Prometheus metrics | `GET /api/metrics` (staff token): calls, turns, handovers by reason, STT/NLU/first-audio histograms, late AI escalations |
| Logs | JSON lines on stdout (`docker compose logs -f agent`). Utterance text and secrets are never logged. Docker rotates logs (10 MB x 5). |
| Audit integrity | `GET /api/audit/verify` (staff token) - hash chain over security-relevant events |

Alert on: `/api/ready` != 200, `handovers_waiting` > 0 for several minutes, `late_escalations`/`turn_timeouts`/`turn_errors` rising, all LLM routes disabled (`/api/admin/health`).

## 5. Rate limiting and abuse controls (already built in)

nginx: 20 req/s per IP on `/api`, 6/min on staff login, 8 websocket connections per IP.
Agent: max concurrent calls (`MAX_CONCURRENT_CALLS`), per-IP calls (`MAX_CALLS_PER_IP`), 30 s audio cap, utterances per minute,
call duration and idle timeouts, PIN lockout (5 failures / 15 min), cross-origin websocket rejection, 8 failed identity checks / hour / IP.

## 6. Backups and restore

`--profile backup` runs a nightly `pg_dump` to the `backups` volume (14 days retention). Copy that volume off the server regularly.

```bash
docker compose exec backup sh /backup.sh once                              # take a backup now
gunzip -c triage-YYYYmmdd-HHMMSS.sql.gz | docker compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB   # restore
```

Test a restore before you rely on backups. The vector index and TTS cache are rebuildable and need no backup.

## 7. Updates and rollback

```bash
git pull && DOMAIN=... docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# rollback: git checkout <previous tag> and run the same command; restore the DB from backup only if a migration broke it
```

Schema is created with `create_all` (no migrations yet). Introduce Alembic before the first schema change in production.

## 8. Scaling notes

One agent process handles roughly 10 concurrent calls on 4 vCPUs (TTS CPU is the limit; a GPU or a faster TTS raises it). The agent keeps
live-call state in memory, so scale **up** first; scaling out needs sticky sessions plus moving the hand-over hub to Redis.

## 9. Before real use (not optional)

1. Clinician review and written sign-off of `agent/app/safety/redflags.py`, `scripts.py`, the knowledge documents, and the evaluation expectations in `agent/seed/`.
2. Privacy/compliance review. Speech audio and transcripts go to the configured cloud STT/LLM providers (Groq/OpenAI) - check their terms and your
   jurisdiction's rules, or switch to `STT_ROUTE_ORDER=local` and an on-premises LLM. Use synthetic data until approved.
3. Hospital policy for caller identity verification (name + date of birth is weak) and for recording notices/consent.
4. A real telephony/hand-over path (SIP/PBX) and staff authentication (SSO) replacing the demo PIN.
5. A staffed escalation process: an unattended hand-over queue is a patient-safety hazard.
6. Urdu voice: there is no suitably licensed free Urdu voice; Urdu callers are currently handed to staff.

## 10. Deployed instance: shared-proxy layout (protons.upscaleleads.cloud)

The VPS already runs another project with its own Caddy on ports 80/443, so this stack publishes **no host ports** and is reached
through that Caddy:

* Code: `/opt/protons` (cloned from GitHub). Secrets: `/opt/protons/.env` (chmod 600, never committed). Staff PIN: `/root/protons_staff_pin.txt`.
* Start/update: `cd /opt/protons && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
* Edge network: only the `hania-web` container joins `protons_edge`; the existing Caddy is attached with
  `docker network connect protons_edge pusula-caddy-1` and has the site block from `deploy/Caddyfile.shared-proxy` appended to `/etc/pusula/Caddyfile`
  (backup: `/etc/pusula/Caddyfile.bak-protons-*`). Reload: `docker exec pusula-caddy-1 caddy reload --config /etc/caddy/Caddyfile`.
* **If the other project's Caddy container is recreated**, re-attach it (`docker network connect protons_edge pusula-caddy-1`) or the site returns 502 until you do.
* Rollback of the proxy change: restore the backup Caddyfile and reload; `docker compose ... down` removes only this project's containers.
