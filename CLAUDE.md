# Miss Floss — Dental Voice CRM

AI voice agent + dashboard for dental clinics (missfloss.ai). Rebranded fork of the
RapidX outbound caller (Dogra-style) system, for Anmol Anand & Rutvik.

> **Deploying? Read `DEPLOY_MISSFLOSS.md`** — full plain-English guide: local on a
> computer, on a VPS (Docker / Coolify / Nginx+HTTPS), and Telnyx number setup.

## Stack
- **Backend**: FastAPI (`server.py`) + LiveKit agent worker (`agent.py`), Gemini Live (single-node STT+LLM+TTS, low latency).
- **Telephony**: Vobiz (dev) or **Telnyx** (clinic / international, $1/number). Switch via `ACTIVE_TELEPHONY_PROVIDER` + `POST /api/setup/trunk/telnyx`.
- **DB**: Supabase (Postgres). Dev points at the shared `outbound-caller` project; SWAP to the clinic's own Supabase at delivery (build-with-our-creds rule).
- **Auth**: doctor login/logout, PBKDF2 passwords, HMAC-signed cookie sessions (`auth.py`). `doctors` table in Supabase.

## Folder / key files
- `server.py` — API + auth + UI serving. Dashboard at `/` is gated; redirects to `/login`.
- `auth.py` — password hashing, session tokens, doctor records.
- `agent.py` — LiveKit worker; outbound dial + inbound handling; Gemini Live session.
- `make_call.py` — CLI to dispatch an outbound call.
- `ui/index.html` — dashboard (Stats, Calls, Appointments, CRM, Campaigns, Agents, Live Link). Cyan/white theme.
- `ui/login.html` — doctor sign-in / owner self-registration.
- `ui/talk.html` — browser "Talk to Agent" page (no phone needed).
- `supabase_schema.sql` — base tables. Doctor-auth + `call_logs.direction` added via migration.

## Branding
- Name: **Miss Floss**. Primary color **cyan** (`--accent #0891b2`, `--accent2 #06b6d4`) on **white**. Never dark theme.

## Auth flow
- First run: owner self-registers at `/login` (create owner account).
- After that, adding doctors requires `SETUP_TOKEN` (env) via `POST /api/auth/register`.
- Session cookie `mf_session` (HttpOnly). Set `COOKIE_SECURE=true` behind HTTPS.
- Seeded dev account: `anmol@missfloss.ai` / `MissFloss2026`.

## Run locally
```
cd ~/iCloud/website/missfloss && source venv/bin/activate
export $(grep -v '^#' .env | xargs)
uvicorn server:app --host 0.0.0.0 --port 8100   # dashboard
python agent.py start                            # voice worker (separate shell)
```
Dashboard: http://localhost:8100  (login → dashboard)

## Telephony setup (Telnyx)
1. portal.telnyx.com → Voice → SIP Connections → Create (Credentials auth).
2. Put username/password/number in `.env` (`TELNYX_*`).
3. `POST /api/setup/trunk/telnyx` → creates LiveKit outbound trunk, sets `OUTBOUND_TRUNK_ID`.
4. Inbound: point the Telnyx number's voice at `LIVEKIT_SIP_ENDPOINT`, then `POST /api/setup/trunk/telnyx/inbound`.

## Deploy (production)
- GitHub repo → Coolify on a VPS (Dockerfile included). NOT local tunnels.
- At delivery: swap Supabase, LiveKit, Telnyx, Gemini keys to the clinic's own. Set `COOKIE_SECURE=true`.

## Still to wire (needs client inputs)
- S3 call recordings: set `AWS_*` / `S3_ENDPOINT` (egress code exists in `agent.py`).
- Real Telnyx credentials for the clinic's numbers.
- HIPAA hardening (BAA, encryption at rest, audit log) — secondary per scope.
