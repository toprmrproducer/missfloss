# OutboundAI — Complete One-Shot Build Specification

> **Instructions for the AI reading this:**
> Build this system exactly as described. Every file, every function, every line of config is specified below.
> Do not skip anything. Do not simplify. Do not substitute libraries. Build it precisely.
> This document is complete and self-contained — no external repo is required.

---

## 0. What You Are Building

A **production-grade AI outbound voice calling SaaS platform** that:

- Dials phone numbers automatically via SIP telephony (Vobiz)
- Connects each call to a **Gemini Live real-time AI voice agent** (sub-100ms latency, zero separate STT/TTS)
- Books appointments into Supabase and optionally into **Cal.com**
- Runs mass **campaign calling** with APScheduler (once / daily / weekdays at a scheduled time)
- Maintains a **CRM** with per-contact history, editable notes, and AI-extracted memory
- Remembers key facts about each lead across calls using Gemini Flash compression
- Records calls to S3-compatible storage via LiveKit Egress
- Provides a **full-stack single-page dashboard**: single call, batch CSV, campaigns, AI prompt editor, appointments, call logs, CRM, agent profiles, settings (BYOK), live logs, charts
- Persists everything to **Supabase** (zero local SQLite in production)
- Supports **named agent profiles** (different voice + model + prompt + tools per campaign or call)
- Deploys to **Coolify** (self-hosted PaaS on a VPS) via Docker

**Tech stack:**
- Python 3.11
- LiveKit Agents 1.x (voice AI orchestration)
- Google Gemini Live API (`gemini-3.1-flash-live-preview`)
- Vobiz SIP trunk (telephony — dial out)
- FastAPI + Uvicorn (REST API)
- Supabase (PostgreSQL database)
- APScheduler (campaign cron scheduling)
- Chart.js (dashboard charts, via CDN)
- Vanilla HTML/CSS/JS (single-file dashboard, no build step)
- Docker + Coolify (deployment)

---

## 1. File Structure

Create every file listed here. No extras needed.

```
/
├── agent.py              ← LiveKit worker — Gemini Live voice AI entrypoint
├── server.py             ← FastAPI backend — all REST endpoints + APScheduler
├── db.py                 ← All Supabase async DB operations
├── tools.py              ← LLM function tools (9 total)
├── prompts.py            ← System prompt template + build_prompt()
├── start.sh              ← Production startup: uvicorn port 8000 + agent worker
├── Dockerfile            ← CMD: sh start.sh
├── requirements.txt      ← All Python dependencies
├── supabase_schema.sql   ← Run once in Supabase SQL Editor
├── .env                  ← Secrets — never commit, always .gitignore
├── .gitignore
└── ui/
    └── index.html        ← Single-file dashboard (all CSS + JS inline)
```

---

## 2. Environment Variables

### `.env` file (local development):

```env
# ── LiveKit Cloud ── cloud.livekit.io → Project → Keys
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Google Gemini ── aistudio.google.com/app/apikey
GOOGLE_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_TTS_VOICE=Aoede
USE_GEMINI_REALTIME=true

# ── Vobiz SIP telephony ── vobiz.ai
VOBIZ_SIP_DOMAIN=xxxxxxxx.sip.vobiz.ai
VOBIZ_USERNAME=your_username
VOBIZ_PASSWORD=your_password
VOBIZ_OUTBOUND_NUMBER=+919876543210
OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxxxxxx
DEFAULT_TRANSFER_NUMBER=+919876543210

# ── Supabase ── supabase.com → Project Settings → API
SUPABASE_URL=https://xxxxxxxxxxxxxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# ── S3 / Supabase Storage (call recordings — optional) ──
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_ENDPOINT_URL=https://xxxxxxxxxxxxxxxx.supabase.co/storage/v1/s3
S3_REGION=ap-northeast-1
S3_BUCKET=call-recordings

# ── Cal.com (calendar booking sync — optional) ──
CALCOM_API_KEY=cal_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CALCOM_EVENT_TYPE_ID=123456
CALCOM_TIMEZONE=Asia/Kolkata

# ── Twilio SMS (confirmation texts — optional) ──
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+1234567890

# ── Deepgram (pipeline fallback STT — optional) ──
DEEPGRAM_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### `.gitignore`:

```
.env
__pycache__/
*.pyc
*.pyo
*.db
*.sqlite
*.log
venv/
.venv/
node_modules/
*.egg-info/
dist/
build/
.DS_Store
```

---

## 3. Supabase Schema

Run this **once** in Supabase Dashboard → SQL Editor. Every statement uses `IF NOT EXISTS` — safe to re-run.

```sql
-- ═══════════════════════════════════════════════════════
-- OutboundAI — Complete Database Schema
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    service TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'booked',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_logs (
    id TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL,
    lead_name TEXT,
    outcome TEXT,
    reason TEXT,
    duration_seconds INTEGER,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS error_logs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL,
    detail TEXT,
    timestamp TEXT NOT NULL
);

ALTER TABLE appointments  DISABLE ROW LEVEL SECURITY;
ALTER TABLE call_logs     DISABLE ROW LEVEL SECURITY;
ALTER TABLE settings      DISABLE ROW LEVEL SECURITY;
ALTER TABLE error_logs    DISABLE ROW LEVEL SECURITY;

ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS recording_url TEXT;
ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS notes TEXT;

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    contacts_json TEXT NOT NULL DEFAULT '[]',
    schedule_type TEXT NOT NULL DEFAULT 'once',
    schedule_time TEXT DEFAULT '09:00',
    call_delay_seconds INTEGER DEFAULT 3,
    system_prompt TEXT,
    created_at TEXT NOT NULL,
    last_run_at TEXT,
    total_dispatched INTEGER DEFAULT 0,
    total_failed INTEGER DEFAULT 0
);
ALTER TABLE campaigns DISABLE ROW LEVEL SECURITY;

ALTER TABLE appointments ADD COLUMN IF NOT EXISTS calcom_booking_uid TEXT;

CREATE TABLE IF NOT EXISTS contact_memory (
    id TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL,
    insight TEXT NOT NULL,
    created_at TEXT NOT NULL
);
ALTER TABLE contact_memory DISABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_contact_memory_phone ON contact_memory (phone_number);

ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

CREATE TABLE IF NOT EXISTS agent_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    voice TEXT NOT NULL DEFAULT 'Aoede',
    model TEXT NOT NULL DEFAULT 'gemini-3.1-flash-live-preview',
    system_prompt TEXT,
    enabled_tools TEXT DEFAULT '[]',
    is_default INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
ALTER TABLE agent_profiles DISABLE ROW LEVEL SECURITY;
```

---

## 4. `requirements.txt`

```
livekit-agents>=1.0.0
livekit-api>=0.8.0
livekit-plugins-google>=1.0.0
livekit-plugins-deepgram>=0.8.0
livekit-plugins-silero>=0.8.0
livekit-plugins-noise-cancellation
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
supabase>=2.0.0
httpx>=0.25.0
python-dotenv>=1.0.0
apscheduler>=3.10.0
google-api-python-client>=2.100.0
google-auth-oauthlib>=1.0.0
twilio>=8.0.0
certifi>=2024.0.0
```

---

## 5. `Dockerfile`

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data
ENV DB_PATH=/data/appointments.db

EXPOSE 8000

CMD ["sh", "start.sh"]
```

---

## 6. `start.sh`

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "🚀 Starting Outbound Mass Caller..."

if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "📋 Configuration:"
echo "   LiveKit: ${LIVEKIT_URL}"
echo "   Gemini: ${GEMINI_MODEL:-gemini-3.1-flash-live-preview}"
echo "   Supabase: ${SUPABASE_URL}"

echo "🌐 Starting FastAPI server on port 8000..."
uvicorn server:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!

sleep 2

echo "🤖 Starting LiveKit agent worker..."
python agent.py start

kill $SERVER_PID 2>/dev/null || true
```

---

## 7. `prompts.py`

```python
DEFAULT_SYSTEM_PROMPT = """\
You are Priya, a sharp, warm, and professional appointment booking assistant calling on behalf of {business_name}.

Your single goal: book a {service_type} appointment for {lead_name}.

━━━ CRITICAL: SPEAK FIRST ━━━
The moment the call connects, you speak immediately. Do NOT wait for the lead to say anything.
Open with: "Hi, am I speaking with {lead_name}?"

━━━ CALL FLOW ━━━

STEP 1 — CONFIRM IDENTITY
"Hi, am I speaking with {lead_name}?"
• Wrong person  → apologise briefly → end_call(outcome='wrong_number', reason='wrong person answered')
• Voicemail/IVR → leave message: "Hi {lead_name}, this is Priya from {business_name} regarding your {service_type}. Please call us back — have a great day!" → end_call(outcome='voicemail', reason='left voicemail')
• No answer / silence for 5 s → end_call(outcome='no_answer', reason='no response')

STEP 2 — INTRODUCE
"Great! I'm Priya from {business_name}. We have some slots open this week for {service_type} and I wanted to get you booked in — takes less than a minute."

STEP 3 — QUALIFY INTEREST
Ask one short question. If yes → STEP 4.
If no → ask once if a different time works. Second refusal → end_call(outcome='not_interested', reason='lead declined twice').

STEP 4 — FIND A SLOT
Ask: "What day and time works best for you?"
ALWAYS call check_availability(date, time) before confirming anything.
If slot unavailable → "That one's taken — how about [next available]?"

STEP 5 — BOOK
Once lead verbally agrees to date + time:
1. Call book_appointment(name, phone, date, time, service)
2. Call send_sms_confirmation(phone, "Your {service_type} at {business_name} is confirmed for [date] at [time]. See you then!")

STEP 6 — CLOSE
"Perfect, you're all set for [date] at [time]! Is there anything else before I let you go?"
→ end_call(outcome='booked', reason='appointment confirmed')

━━━ OBJECTION HANDLING ━━━

"I'm busy right now"      → "Completely fine — I'll be quick. We have a slot tomorrow morning, would that work?"
"Not interested"          → "No worries at all. If anything changes, feel free to call us. Have a great day!" → end_call(outcome='not_interested')
"Who gave you my number?" → "We have you on file from a previous inquiry with {business_name}. Apologies if the timing is off."
"Stop calling"            → "Absolutely, I'll make a note right now. Sorry for the interruption!" → end_call(outcome='not_interested', reason='requested removal')
"Transfer to a human"     → transfer_to_human(reason='lead requested human agent')
"Are you a bot/AI?"       → "I'm a virtual assistant for {business_name} — I can still get you fully booked in though! Shall we find a time?"
"Call me later"           → "Of course — what time works best for a callback?" → remember_details("Requested callback") → end_call(outcome='callback_requested', reason='will call back')

━━━ STYLE RULES ━━━

• Maximum 1–2 short sentences per turn. Cut every filler word.
• NEVER start with "Certainly!", "Of course!", "Absolutely!" or any filler opener.
• NEVER say "As an AI" unless directly and persistently asked.
• Match the lead's language — Hindi/English code-switching is fine.
• If lead says "hold on" or goes quiet, wait silently — do not fill silence.
• Always sound like a real person: casual, warm, confident.
• Respond in under 10 words where possible.
• Use the lookup_contact tool at the start of every call to retrieve prior history.
• Use remember_details any time the lead shares something useful (preferences, objections, timing).

━━━ TOOL USAGE RULES ━━━

• lookup_contact  → call at call start ONLY (before any conversation)
• check_availability → ALWAYS before confirming a slot
• book_appointment → only after verbal confirmation
• end_call → ALWAYS call this at call end (never just hang up silently)
• remember_details → use freely throughout — more context = better future calls
"""


def build_prompt(
    lead_name: str = "there",
    business_name: str = "our company",
    service_type: str = "our service",
    custom_prompt: str = None,
) -> str:
    """Interpolate lead/business details into the prompt template."""
    template = custom_prompt if custom_prompt else DEFAULT_SYSTEM_PROMPT
    try:
        return template.format(
            lead_name=lead_name,
            business_name=business_name,
            service_type=service_type,
        )
    except KeyError:
        return template
```

---

## 8. `db.py` — Complete

```python
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

# ---------------------------------------------------------------------------
# DEFAULTS — all loaded from environment variables only.
# Never hardcode real credentials here. Use Coolify env vars or .env file.
# ---------------------------------------------------------------------------
DEFAULTS = {
    "LIVEKIT_URL":             os.getenv("LIVEKIT_URL", ""),
    "LIVEKIT_API_KEY":         os.getenv("LIVEKIT_API_KEY", ""),
    "LIVEKIT_API_SECRET":      os.getenv("LIVEKIT_API_SECRET", ""),
    "GOOGLE_API_KEY":          os.getenv("GOOGLE_API_KEY", ""),
    "GEMINI_MODEL":            os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview"),
    "GEMINI_TTS_VOICE":        os.getenv("GEMINI_TTS_VOICE", "Aoede"),
    "USE_GEMINI_REALTIME":     os.getenv("USE_GEMINI_REALTIME", "true"),
    "VOBIZ_SIP_DOMAIN":        os.getenv("VOBIZ_SIP_DOMAIN", ""),
    "VOBIZ_USERNAME":          os.getenv("VOBIZ_USERNAME", ""),
    "VOBIZ_PASSWORD":          os.getenv("VOBIZ_PASSWORD", ""),
    "VOBIZ_OUTBOUND_NUMBER":   os.getenv("VOBIZ_OUTBOUND_NUMBER", ""),
    "OUTBOUND_TRUNK_ID":       os.getenv("OUTBOUND_TRUNK_ID", ""),
    "DEFAULT_TRANSFER_NUMBER": os.getenv("DEFAULT_TRANSFER_NUMBER", ""),
    "SUPABASE_URL":            os.getenv("SUPABASE_URL", ""),
    "SUPABASE_SERVICE_KEY":    os.getenv("SUPABASE_SERVICE_KEY", ""),
    "DEEPGRAM_API_KEY":        os.getenv("DEEPGRAM_API_KEY", ""),
}


def _default(key: str) -> str:
    return os.getenv(key, DEFAULTS.get(key, ""))


SUPABASE_URL = _default("SUPABASE_URL")
SUPABASE_KEY = _default("SUPABASE_SERVICE_KEY")

SENSITIVE_KEYS = {
    "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "GOOGLE_API_KEY",
    "VOBIZ_PASSWORD", "TWILIO_AUTH_TOKEN", "SUPABASE_SERVICE_KEY",
    "AWS_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY", "CALCOM_API_KEY",
    "DEEPGRAM_API_KEY",
}


def _sdb():
    from supabase import create_client
    return create_client(_default("SUPABASE_URL"), _default("SUPABASE_SERVICE_KEY"))


async def _adb():
    from supabase._async.client import create_client
    return await create_client(_default("SUPABASE_URL"), _default("SUPABASE_SERVICE_KEY"))


def init_db() -> None:
    url = os.getenv("SUPABASE_URL", SUPABASE_URL)
    key = os.getenv("SUPABASE_SERVICE_KEY", SUPABASE_KEY)
    if not url or not key:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set.")
        return
    try:
        db = _sdb()
        db.table("settings").select("key").limit(1).execute()
        print("✅ Supabase connected")
    except Exception as exc:
        print(f"⚠️  Supabase connection failed: {exc}")
        print("   Run supabase_schema.sql in your Supabase Dashboard → SQL Editor")


# ── Settings ─────────────────────────────────────────────────────────────────

async def get_all_settings() -> dict:
    db = await _adb()
    result = await db.table("settings").select("key, value").execute()
    KNOWN_KEYS = [
        "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
        "GOOGLE_API_KEY", "GEMINI_MODEL", "GEMINI_TTS_VOICE", "USE_GEMINI_REALTIME",
        "VOBIZ_SIP_DOMAIN", "VOBIZ_USERNAME", "VOBIZ_PASSWORD",
        "VOBIZ_OUTBOUND_NUMBER", "OUTBOUND_TRUNK_ID", "DEFAULT_TRANSFER_NUMBER",
        "DEEPGRAM_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
        "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_ENDPOINT_URL", "S3_REGION", "S3_BUCKET",
        "CALCOM_API_KEY", "CALCOM_EVENT_TYPE_ID", "CALCOM_TIMEZONE",
        "ENABLED_TOOLS",
    ]
    out: dict = {}
    for k in KNOWN_KEYS:
        env_val = _default(k)
        if k in SENSITIVE_KEYS:
            out[k] = {"value": "", "configured": bool(env_val)}
        else:
            out[k] = {"value": env_val, "configured": bool(env_val)}
    for row in (result.data or []):
        k, v = row["key"], row["value"]
        if k == "TEST_KEY":
            continue
        if k in SENSITIVE_KEYS:
            out[k] = {"value": "", "configured": bool(v)}
        else:
            out[k] = {"value": v, "configured": bool(v)}
    return out


async def save_settings(data: dict) -> None:
    db = await _adb()
    updated_at = datetime.now().isoformat()
    rows = [
        {"key": k, "value": str(v), "updated_at": updated_at}
        for k, v in data.items()
        if v is not None and v != ""
    ]
    if rows:
        await db.table("settings").upsert(rows, on_conflict="key").execute()


async def get_setting(key: str, default: str = "") -> str:
    db = await _adb()
    result = await db.table("settings").select("value").eq("key", key).maybe_single().execute()
    if result and result.data:
        return result.data["value"]
    return _default(key) or default


async def set_setting(key: str, value: str) -> None:
    db = await _adb()
    await db.table("settings").upsert(
        {"key": key, "value": value, "updated_at": datetime.now().isoformat()},
        on_conflict="key",
    ).execute()


async def get_enabled_tools() -> list:
    raw = await get_setting("ENABLED_TOOLS", "")
    if not raw:
        return []
    try:
        import json
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception:
        return []


# ── Error logs ────────────────────────────────────────────────────────────────

async def log_error(source: str, message: str, detail: str = "", level: str = "error") -> None:
    try:
        db = await _adb()
        await db.table("error_logs").insert({
            "id": str(uuid.uuid4()),
            "source": source,
            "level": level,
            "message": message[:500],
            "detail": detail[:2000],
            "timestamp": datetime.now().isoformat(),
        }).execute()
    except Exception:
        pass


async def get_errors(limit: int = 100) -> list:
    db = await _adb()
    result = await db.table("error_logs").select("*").order("timestamp", desc=True).limit(limit).execute()
    return result.data or []


async def get_logs(level: Optional[str] = None, source: Optional[str] = None, limit: int = 200) -> list:
    db = await _adb()
    query = db.table("error_logs").select("*").order("timestamp", desc=True).limit(limit)
    if level:
        query = query.eq("level", level)
    if source:
        query = query.eq("source", source)
    result = await query.execute()
    return result.data or []


async def clear_errors() -> None:
    db = await _adb()
    await db.table("error_logs").delete().neq("id", "").execute()


# ── Appointments ──────────────────────────────────────────────────────────────

async def insert_appointment(name: str, phone: str, date: str, time: str, service: str) -> str:
    full_id = str(uuid.uuid4())
    booking_id = full_id[:8].upper()
    db = await _adb()
    await db.table("appointments").insert({
        "id": full_id, "name": name, "phone": phone,
        "date": date, "time": time, "service": service,
        "status": "booked", "created_at": datetime.now().isoformat(),
    }).execute()
    return booking_id


async def check_slot(date: str, time: str) -> bool:
    """Returns True if slot is available (no existing booking)."""
    db = await _adb()
    result = await (
        db.table("appointments").select("id")
        .eq("date", date).eq("time", time).eq("status", "booked")
        .maybe_single().execute()
    )
    return result.data is None


async def get_next_available(date: str, time: str) -> str:
    try:
        dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        dt = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    for _ in range(7 * 24):
        dt += timedelta(hours=1)
        if 9 <= dt.hour < 18:
            if await check_slot(dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")):
                return f"{dt.strftime('%Y-%m-%d')} at {dt.strftime('%H:%M')}"
    return "no open slots found in the next 7 days"


async def get_all_appointments(date_filter: Optional[str] = None) -> list:
    db = await _adb()
    query = db.table("appointments").select("*").order("date").order("time")
    if date_filter:
        query = query.eq("date", date_filter)
    result = await query.execute()
    return result.data or []


async def cancel_appointment(appointment_id: str) -> bool:
    db = await _adb()
    result = await (
        db.table("appointments").update({"status": "cancelled"})
        .eq("id", appointment_id).eq("status", "booked").execute()
    )
    return len(result.data or []) > 0


async def get_appointments_by_phone(phone: str) -> list:
    db = await _adb()
    result = await db.table("appointments").select("*").eq("phone", phone).order("date", desc=True).execute()
    return result.data or []


# ── Call logs ─────────────────────────────────────────────────────────────────

async def log_call(
    phone_number: str, lead_name: Optional[str], outcome: str, reason: str,
    duration_seconds: int, recording_url: Optional[str] = None, notes: Optional[str] = None,
) -> None:
    db = await _adb()
    row: dict = {
        "id": str(uuid.uuid4()), "phone_number": phone_number, "lead_name": lead_name,
        "outcome": outcome, "reason": reason, "duration_seconds": duration_seconds,
        "timestamp": datetime.now().isoformat(),
    }
    if recording_url:
        row["recording_url"] = recording_url
    if notes:
        row["notes"] = notes
    await db.table("call_logs").insert(row).execute()


async def get_all_calls(page: int = 1, limit: int = 20) -> list:
    db = await _adb()
    offset = (page - 1) * limit
    result = await db.table("call_logs").select("*").order("timestamp", desc=True).range(offset, offset + limit - 1).execute()
    return result.data or []


async def get_calls_by_phone(phone: str) -> list:
    db = await _adb()
    result = await db.table("call_logs").select("*").eq("phone_number", phone).order("timestamp", desc=True).execute()
    return result.data or []


async def update_call_notes(call_id: str, notes: str) -> bool:
    db = await _adb()
    result = await db.table("call_logs").update({"notes": notes}).eq("id", call_id).execute()
    return len(result.data or []) > 0


async def get_contacts() -> list:
    db = await _adb()
    result = await db.table("call_logs").select("*").order("timestamp", desc=True).execute()
    rows = result.data or []
    contacts: dict = {}
    for row in rows:
        phone = row["phone_number"]
        if phone not in contacts:
            contacts[phone] = {
                "phone_number": phone, "lead_name": row.get("lead_name"),
                "total_calls": 0, "booked": 0,
                "last_call": row["timestamp"], "last_outcome": row.get("outcome"),
            }
        contacts[phone]["total_calls"] += 1
        if row.get("outcome") == "booked":
            contacts[phone]["booked"] += 1
    return sorted(contacts.values(), key=lambda c: c["last_call"], reverse=True)


# ── Stats ─────────────────────────────────────────────────────────────────────

async def get_stats() -> dict:
    db = await _adb()
    rows = (await db.table("call_logs").select("outcome, duration_seconds, timestamp").execute()).data or []
    total_calls    = len(rows)
    booked         = sum(1 for r in rows if r.get("outcome") == "booked")
    not_interested = sum(1 for r in rows if r.get("outcome") == "not_interested")
    durations      = [r["duration_seconds"] for r in rows if r.get("duration_seconds")]
    avg_dur        = sum(durations) / len(durations) if durations else 0
    booking_rate   = round((booked / total_calls * 100) if total_calls else 0, 1)
    # Outcomes breakdown
    outcomes: dict = {}
    for r in rows:
        o = r.get("outcome") or "unknown"
        outcomes[o] = outcomes.get(o, 0) + 1
    # Timeline: calls per day last 14 days
    daily: dict = defaultdict(int)
    for r in rows:
        ts = (r.get("timestamp") or "")[:10]
        if ts:
            daily[ts] += 1
    today = datetime.now().date()
    timeline = [{"date": (today - timedelta(days=i)).isoformat(), "count": daily.get((today - timedelta(days=i)).isoformat(), 0)} for i in range(13, -1, -1)]
    # Avg duration by outcome
    dur_sum: dict = defaultdict(float)
    dur_cnt: dict = defaultdict(int)
    for r in rows:
        o = r.get("outcome") or "unknown"
        sec = r.get("duration_seconds")
        if sec:
            dur_sum[o] += sec
            dur_cnt[o] += 1
    duration_by_outcome = {o: dur_sum[o] / dur_cnt[o] for o in dur_sum}
    return {
        "total_calls": total_calls, "booked": booked, "not_interested": not_interested,
        "avg_duration_seconds": round(avg_dur, 1), "booking_rate_percent": booking_rate,
        "outcomes": outcomes, "timeline": timeline, "duration_by_outcome": duration_by_outcome,
    }


# ── Campaigns ─────────────────────────────────────────────────────────────────

async def create_campaign(
    name: str, contacts_json: str, schedule_type: str = "once",
    schedule_time: str = "09:00", call_delay_seconds: int = 3,
    system_prompt: Optional[str] = None, agent_profile_id: Optional[str] = None,
) -> str:
    campaign_id = str(uuid.uuid4())
    db = await _adb()
    row: dict = {
        "id": campaign_id, "name": name, "status": "active",
        "contacts_json": contacts_json, "schedule_type": schedule_type,
        "schedule_time": schedule_time, "call_delay_seconds": call_delay_seconds,
        "created_at": datetime.now().isoformat(), "total_dispatched": 0, "total_failed": 0,
    }
    if system_prompt:
        row["system_prompt"] = system_prompt
    if agent_profile_id:
        row["agent_profile_id"] = agent_profile_id
    await db.table("campaigns").insert(row).execute()
    return campaign_id


async def get_all_campaigns() -> list:
    db = await _adb()
    result = await db.table("campaigns").select("*").order("created_at", desc=True).execute()
    return result.data or []


async def get_campaign(campaign_id: str) -> Optional[dict]:
    db = await _adb()
    result = await db.table("campaigns").select("*").eq("id", campaign_id).maybe_single().execute()
    return result.data if result else None


async def update_campaign_status(campaign_id: str, status: str) -> bool:
    db = await _adb()
    result = await db.table("campaigns").update({"status": status}).eq("id", campaign_id).execute()
    return len(result.data or []) > 0


async def update_campaign_run_stats(campaign_id: str, dispatched: int, failed: int) -> None:
    db = await _adb()
    await db.table("campaigns").update({
        "last_run_at": datetime.now().isoformat(),
        "total_dispatched": dispatched, "total_failed": failed, "status": "completed",
    }).eq("id", campaign_id).execute()


async def delete_campaign(campaign_id: str) -> bool:
    db = await _adb()
    result = await db.table("campaigns").delete().eq("id", campaign_id).execute()
    return len(result.data or []) > 0


# ── Contact Memory ────────────────────────────────────────────────────────────

async def add_contact_memory(phone: str, insight: str) -> None:
    db = await _adb()
    await db.table("contact_memory").insert({
        "id": str(uuid.uuid4()), "phone_number": phone,
        "insight": insight[:1000], "created_at": datetime.now().isoformat(),
    }).execute()


async def get_contact_memory(phone: str) -> list:
    db = await _adb()
    result = await (
        db.table("contact_memory").select("insight, created_at")
        .eq("phone_number", phone).order("created_at", desc=True).limit(20).execute()
    )
    return result.data or []


async def compress_contact_memory(phone: str, compressed: str) -> None:
    db = await _adb()
    await db.table("contact_memory").delete().eq("phone_number", phone).execute()
    await db.table("contact_memory").insert({
        "id": str(uuid.uuid4()), "phone_number": phone,
        "insight": compressed[:2000], "created_at": datetime.now().isoformat(),
    }).execute()


# ── Agent Profiles ────────────────────────────────────────────────────────────

async def get_all_agent_profiles() -> list:
    db = await _adb()
    result = await db.table("agent_profiles").select("*").order("created_at").execute()
    return result.data or []


async def get_agent_profile(profile_id: str) -> Optional[dict]:
    db = await _adb()
    result = await db.table("agent_profiles").select("*").eq("id", profile_id).maybe_single().execute()
    return result.data if result else None


async def create_agent_profile(
    name: str, voice: str = "Aoede", model: str = "gemini-3.1-flash-live-preview",
    system_prompt: Optional[str] = None, enabled_tools: str = "[]", is_default: bool = False,
) -> str:
    profile_id = str(uuid.uuid4())
    db = await _adb()
    if is_default:
        await db.table("agent_profiles").update({"is_default": 0}).neq("id", "placeholder").execute()
    await db.table("agent_profiles").insert({
        "id": profile_id, "name": name, "voice": voice, "model": model,
        "system_prompt": system_prompt, "enabled_tools": enabled_tools,
        "is_default": 1 if is_default else 0, "created_at": datetime.now().isoformat(),
    }).execute()
    return profile_id


async def update_agent_profile(profile_id: str, updates: dict) -> bool:
    db = await _adb()
    result = await db.table("agent_profiles").update(updates).eq("id", profile_id).execute()
    return len(result.data or []) > 0


async def delete_agent_profile(profile_id: str) -> bool:
    db = await _adb()
    result = await db.table("agent_profiles").delete().eq("id", profile_id).execute()
    return len(result.data or []) > 0


async def set_default_agent_profile(profile_id: str) -> None:
    db = await _adb()
    await db.table("agent_profiles").update({"is_default": 0}).neq("id", "placeholder").execute()
    await db.table("agent_profiles").update({"is_default": 1}).eq("id", profile_id).execute()
```

---

## 9. `tools.py` — Complete (9 Tools)

```python
import asyncio
import logging
import os
import time
from typing import Optional

from livekit import agents, api
from livekit.agents import llm

from db import (
    check_slot, get_next_available, insert_appointment, log_call, log_error,
    get_calls_by_phone, get_appointments_by_phone,
    add_contact_memory, get_contact_memory, compress_contact_memory,
)

logger = logging.getLogger("appointment-tools")


async def _log(msg: str, detail: str = "", level: str = "info") -> None:
    try:
        await log_error("agent", msg, detail, level)
    except Exception:
        pass


class AppointmentTools(llm.ToolContext):
    """All function tools available to the appointment-booking agent."""

    def __init__(self, ctx: agents.JobContext, phone_number: Optional[str] = None, lead_name: Optional[str] = None):
        self.ctx = ctx
        self.phone_number = phone_number
        self.lead_name = lead_name
        self._call_start_time = time.time()
        self._sip_domain = os.getenv("VOBIZ_SIP_DOMAIN", "")
        self.recording_url: Optional[str] = None
        super().__init__(tools=[])

    def build_tool_list(self, enabled: list) -> list:
        """Return tool methods filtered by the enabled list. Empty list = all enabled."""
        all_methods = [
            self.check_availability, self.book_appointment, self.end_call,
            self.transfer_to_human, self.send_sms_confirmation, self.lookup_contact,
            self.remember_details, self.book_calcom, self.cancel_calcom,
        ]
        if not enabled:
            return all_methods
        name_map = {m.__name__: m for m in all_methods}
        return [name_map[n] for n in enabled if n in name_map]

    @llm.function_tool
    async def check_availability(self, date: str, time: str) -> str:
        """
        Check whether a date/time slot is available for booking.
        Call this BEFORE attempting to book whenever the lead proposes a date/time.
        date format: YYYY-MM-DD  |  time format: HH:MM (24-hour)
        Returns 'available' or 'unavailable: next available slot is <slot>'.
        """
        try:
            if await check_slot(date, time):
                return "available"
            next_slot = await get_next_available(date, time)
            return f"unavailable: next available slot is {next_slot}"
        except Exception as exc:
            return "Unable to check availability right now — please suggest a date and I will confirm."

    @llm.function_tool
    async def book_appointment(self, name: str, phone: str, date: str, time: str, service: str) -> str:
        """
        Book an appointment after the lead has verbally confirmed date, time, and service.
        Call ONLY after the lead confirms all details.
        name: lead's full name | phone: with country code | date: YYYY-MM-DD | time: HH:MM | service: type
        """
        try:
            booking_id = await insert_appointment(name, phone, date, time, service)
            return f"Confirmed! Booking ID: {booking_id}. See you on {date} at {time} for {service}."
        except Exception as exc:
            return "Technical issue saving the booking. Our team will confirm shortly."

    @llm.function_tool
    async def end_call(self, outcome: str, reason: str = "") -> str:
        """
        End the call and log the outcome. ALWAYS call this before the call ends.
        outcome: 'booked' | 'not_interested' | 'wrong_number' | 'voicemail' | 'no_answer' | 'callback_requested'
        reason: brief description
        """
        duration = int(time.time() - self._call_start_time)
        try:
            await log_call(
                phone_number=self.phone_number or "unknown",
                lead_name=self.lead_name, outcome=outcome, reason=reason,
                duration_seconds=duration, recording_url=self.recording_url,
            )
        except Exception as exc:
            logger.error("Failed to log call: %s", exc)
        try:
            await self.ctx.room.disconnect()
        except Exception:
            pass
        return "Call ended."

    @llm.function_tool
    async def transfer_to_human(self, reason: str) -> str:
        """
        Transfer the call to a human agent via SIP REFER.
        Call when lead requests a human, is angry, or has a complex issue.
        reason: why you're transferring
        """
        destination = os.getenv("DEFAULT_TRANSFER_NUMBER", "")
        if not destination:
            return "Transfer unavailable: no fallback number configured."
        if "@" not in destination:
            clean = destination.replace("tel:", "").replace("sip:", "")
            destination = f"sip:{clean}@{self._sip_domain}" if self._sip_domain else f"tel:{clean}"
        elif not destination.startswith("sip:"):
            destination = f"sip:{destination}"
        participant_identity = f"sip_{self.phone_number}" if self.phone_number else None
        if not participant_identity:
            for p in self.ctx.room.remote_participants.values():
                participant_identity = p.identity
                break
        if not participant_identity:
            return "Transfer failed: could not identify caller."
        try:
            await self.ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=self.ctx.room.name,
                    participant_identity=participant_identity,
                    transfer_to=destination, play_dialtone=False,
                )
            )
            return "Transferring you to a human agent now. Please hold."
        except Exception as exc:
            return "Transfer failed. Please call us back directly."

    @llm.function_tool
    async def send_sms_confirmation(self, phone: str, message: str) -> str:
        """
        Send SMS confirmation after a successful booking. Skips silently if Twilio not configured.
        phone: lead's phone | message: text to send
        """
        sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        token = os.getenv("TWILIO_AUTH_TOKEN", "")
        from_num = os.getenv("TWILIO_FROM_NUMBER", "")
        if not (sid and token and from_num):
            return "SMS skipped: Twilio not configured."
        try:
            from twilio.rest import Client
            loop = asyncio.get_event_loop()
            client = Client(sid, token)
            await loop.run_in_executor(None, lambda: client.messages.create(body=message, from_=from_num, to=phone))
            return f"SMS sent to {phone}."
        except Exception as exc:
            return "SMS delivery failed, but booking is confirmed."

    @llm.function_tool
    async def lookup_contact(self, phone: str) -> str:
        """
        Look up a contact's full history. Call at the START of every call before engaging.
        phone: the lead's phone number with country code
        Returns call history, appointments, and remembered details.
        """
        try:
            calls = await get_calls_by_phone(phone)
            appointments = await get_appointments_by_phone(phone)
            memories = await get_contact_memory(phone)
            if not calls and not appointments and not memories:
                return f"No history for {phone}. First-time contact."
            lines = [f"Contact history for {phone}:"]
            if memories:
                lines.append(f"\nREMEMBERED ({len(memories)} notes):")
                for m in memories[:10]:
                    lines.append(f"  • {m['insight']}")
            if calls:
                lines.append(f"\nCALL HISTORY ({len(calls)} calls):")
                for c in calls[:5]:
                    ts = (c.get("timestamp") or "")[:16]
                    lines.append(f"  • {ts} — {c.get('outcome','?')}: {c.get('reason','')}")
            if appointments:
                lines.append(f"\nAPPOINTMENTS ({len(appointments)}):")
                for a in appointments[:3]:
                    lines.append(f"  • {a.get('date')} {a.get('time')} — {a.get('service')} [{a.get('status')}]")
            return "\n".join(lines)
        except Exception as exc:
            return "Unable to retrieve contact history."

    @llm.function_tool
    async def remember_details(self, insight: str) -> str:
        """
        Store a key insight about this lead for future calls.
        Use whenever you learn something useful: preferences, objections, timing, family info.
        Examples: "Prefers morning calls", "Has 2 kids, interested in family plan", "Callback in 2 weeks"
        insight: the detail to remember
        """
        if not self.phone_number:
            return "Cannot remember — no phone number for this call."
        try:
            await add_contact_memory(self.phone_number, insight)
            memories = await get_contact_memory(self.phone_number)
            if len(memories) >= 5:
                asyncio.create_task(self._compress_memories())
            return f"Remembered: {insight}"
        except Exception:
            return "Could not save detail."

    async def _compress_memories(self) -> None:
        try:
            memories = await get_contact_memory(self.phone_number)
            if len(memories) < 5:
                return
            import google.generativeai as genai
            api_key = os.getenv("GOOGLE_API_KEY", "")
            if not api_key:
                return
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            bullet_list = "\n".join(f"- {m['insight']}" for m in memories)
            prompt = f"Compress these notes about a sales contact into 3-5 concise bullets. Keep all key facts.\n\n{bullet_list}"
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: model.generate_content(prompt))
            if response.text.strip():
                await compress_contact_memory(self.phone_number, response.text.strip())
        except Exception as exc:
            logger.warning("Memory compression failed: %s", exc)

    @llm.function_tool
    async def book_calcom(self, name: str, email: str, date: str, start_time: str, notes: str = "") -> str:
        """
        Book in Cal.com calendar after book_appointment succeeds.
        name: full name | email: lead's email | date: YYYY-MM-DD | start_time: HH:MM | notes: optional
        """
        api_key = os.getenv("CALCOM_API_KEY", "")
        event_type_id = os.getenv("CALCOM_EVENT_TYPE_ID", "")
        timezone = os.getenv("CALCOM_TIMEZONE", "Asia/Kolkata")
        if not api_key or not event_type_id:
            return "Cal.com not configured — skipping. Add CALCOM_API_KEY and CALCOM_EVENT_TYPE_ID."
        try:
            from datetime import datetime as _dt
            start_dt = _dt.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
            start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.cal.com/v1/bookings",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"eventTypeId": int(event_type_id), "start": start_iso, "timeZone": timezone,
                          "responses": {"name": name, "email": email, "notes": notes},
                          "metadata": {"source": "OutboundAI"}, "language": "en"},
                )
            data = resp.json()
            if resp.status_code not in (200, 201):
                raise ValueError(data.get("message") or str(data))
            uid = data.get("uid", "")
            return f"Cal.com booked. UID: {uid}"
        except Exception as exc:
            return f"Cal.com booking failed: {exc}"

    @llm.function_tool
    async def cancel_calcom(self, booking_uid: str, reason: str = "") -> str:
        """
        Cancel a Cal.com booking by UID.
        booking_uid: from book_calcom | reason: optional
        """
        api_key = os.getenv("CALCOM_API_KEY", "")
        if not api_key:
            return "Cal.com not configured."
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.delete(
                    f"https://api.cal.com/v1/bookings/{booking_uid}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"reason": reason} if reason else {},
                )
            if resp.status_code not in (200, 204):
                raise ValueError(f"HTTP {resp.status_code}")
            return f"Cancelled Cal.com booking {booking_uid}."
        except Exception as exc:
            return f"Cancellation failed: {exc}"
```

---

## 10. `agent.py` — Complete

```python
import asyncio
import json
import logging
import os
import ssl
import certifi
from typing import Optional

from dotenv import load_dotenv

# Patch SSL before any network import
_orig_ssl = ssl.create_default_context
def _certifi_ssl(purpose=ssl.Purpose.SERVER_AUTH, **kwargs):
    if not kwargs.get("cafile") and not kwargs.get("capath") and not kwargs.get("cadata"):
        kwargs["cafile"] = certifi.where()
    return _orig_ssl(purpose, **kwargs)
ssl.create_default_context = _certifi_ssl

from livekit import agents, api, rtc
from livekit.agents import Agent, AgentSession, RoomInputOptions
try:
    from livekit.agents import RoomOptions as _RoomOptions
    _HAS_ROOM_OPTIONS = True
except ImportError:
    _HAS_ROOM_OPTIONS = False
from livekit.plugins import noise_cancellation, silero

from db import init_db, log_error, get_enabled_tools
from prompts import build_prompt
from tools import AppointmentTools

load_dotenv(".env")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbound-agent")

SIP_DOMAIN = os.getenv("VOBIZ_SIP_DOMAIN", "")


async def _log(level: str, msg: str, detail: str = "") -> None:
    if level == "info":      logger.info(msg)
    elif level == "warning": logger.warning(msg)
    else:                    logger.error(msg)
    try:
        await log_error("agent", msg, detail, level)
    except Exception:
        pass


def load_db_settings_to_env() -> None:
    """Load Supabase settings table into os.environ before worker starts."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return
    try:
        from supabase import create_client
        client = create_client(url, key)
        result = client.table("settings").select("key, value").execute()
        for row in (result.data or []):
            if row.get("value"):
                os.environ[row["key"]] = row["value"]
    except Exception as exc:
        logger.warning("Could not load settings from Supabase: %s", exc)


# ── Import Google plugin paths ───────────────────────────────────────────────
_google_realtime = None
_google_beta_realtime = None
_google_llm = None
_google_tts = None

try:
    from livekit.plugins import google as _gp
    try:
        _google_realtime = _gp.realtime.RealtimeModel
        logger.info("Loaded google.realtime.RealtimeModel (stable path)")
    except AttributeError:
        pass
    try:
        _google_beta_realtime = _gp.beta.realtime.RealtimeModel
        logger.info("Loaded google.beta.realtime.RealtimeModel (beta path)")
    except AttributeError:
        pass
    try:
        _google_llm = _gp.LLM
        _google_tts = _gp.TTS
    except AttributeError:
        pass
except ImportError:
    logger.warning("livekit-plugins-google not installed")

_deepgram_stt = None
try:
    from livekit.plugins import deepgram as _dg
    _deepgram_stt = _dg.STT
except ImportError:
    pass


# ── Session factory ──────────────────────────────────────────────────────────

def _build_session(tools: list, system_prompt: str) -> AgentSession:
    """
    Build AgentSession with Gemini Live or pipeline fallback.

    CRITICAL SILENCE-PREVENTION CONFIG — all 3 required:
    1. SessionResumptionConfig(transparent=True) → auto-reconnects after timeout
    2. ContextWindowCompressionConfig → sliding window prevents token limit freeze
    3. RealtimeInputConfig(END_SENSITIVITY_LOW) → less aggressive VAD, 2s silence threshold

    ⚠️ EndSensitivity MUST use full string form: END_SENSITIVITY_LOW (not .LOW — AttributeError!)
    """
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview")
    gemini_voice = os.getenv("GEMINI_TTS_VOICE", "Aoede")
    use_realtime = os.getenv("USE_GEMINI_REALTIME", "true").lower() != "false"

    RealtimeClass = _google_realtime or (_google_beta_realtime if use_realtime else None)

    if use_realtime and RealtimeClass is not None:
        logger.info("SESSION MODE: Gemini Live realtime (%s, voice=%s)", gemini_model, gemini_voice)
        try:
            from google.genai import types as _gt
            _realtime_input_cfg = _gt.RealtimeInputConfig(
                automatic_activity_detection=_gt.AutomaticActivityDetection(
                    end_of_speech_sensitivity=_gt.EndSensitivity.END_SENSITIVITY_LOW,
                    silence_duration_ms=2000,
                    prefix_padding_ms=200,
                ),
            )
            _session_resumption_cfg = _gt.SessionResumptionConfig(transparent=True)
            _ctx_compression_cfg = _gt.ContextWindowCompressionConfig(
                trigger_tokens=25600,
                sliding_window=_gt.SlidingWindow(target_tokens=12800),
            )
            logger.info("Silence-prevention config applied (VAD LOW, transparent resumption, context compression)")
        except Exception as _cfg_err:
            logger.warning("Could not build silence-prevention config: %s", _cfg_err)
            _realtime_input_cfg = None
            _session_resumption_cfg = None
            _ctx_compression_cfg = None

        realtime_kwargs: dict = dict(model=gemini_model, voice=gemini_voice, instructions=system_prompt)
        if _realtime_input_cfg is not None:
            realtime_kwargs["realtime_input_config"]      = _realtime_input_cfg
            realtime_kwargs["session_resumption"]         = _session_resumption_cfg
            realtime_kwargs["context_window_compression"] = _ctx_compression_cfg

        return AgentSession(llm=RealtimeClass(**realtime_kwargs), tools=tools)

    if _google_llm is None:
        raise RuntimeError("No Google AI backend. Run: pip install 'livekit-plugins-google>=1.0'")

    logger.info("SESSION MODE: pipeline (Deepgram STT + Gemini LLM + Google TTS)")
    stt = _deepgram_stt(model="nova-3", language="multi") if _deepgram_stt else None
    tts = _google_tts() if _google_tts else None
    return AgentSession(stt=stt, llm=_google_llm(model="gemini-2.0-flash"), tts=tts, vad=silero.VAD.load(), tools=tools)


class OutboundAssistant(Agent):
    def __init__(self, instructions: str) -> None:
        super().__init__(instructions=instructions)


async def entrypoint(ctx: agents.JobContext) -> None:
    """
    Main entrypoint. Called per job. Reads metadata JSON from ctx.job.metadata.

    DIAL-FIRST PATTERN — CRITICAL:
    Start Gemini Live ONLY after create_sip_participant(wait_until_answered=True) completes.
    If you start the session during ring time (~20-30s), the Gemini idle timeout fires
    and the session dies silently before the call is even answered.

    NO close_on_disconnect — SIP legs have brief audio dropouts that look like disconnects.
    Instead, watch participant_disconnected event for the specific SIP identity.
    """
    await _log("info", f"Job started — room: {ctx.room.name}")

    phone_number: Optional[str] = None
    lead_name = "there"
    business_name = "our company"
    service_type = "our service"
    custom_prompt: Optional[str] = None
    voice_override: Optional[str] = None
    model_override: Optional[str] = None
    tools_override: Optional[str] = None

    if ctx.job.metadata:
        try:
            data = json.loads(ctx.job.metadata)
            phone_number   = data.get("phone_number")
            lead_name      = data.get("lead_name", lead_name)
            business_name  = data.get("business_name", business_name)
            service_type   = data.get("service_type", service_type)
            custom_prompt  = data.get("system_prompt")
            voice_override = data.get("voice_override")
            model_override = data.get("model_override")
            tools_override = data.get("tools_override")
        except (json.JSONDecodeError, AttributeError):
            await _log("warning", "Invalid JSON in job metadata")

    await _log("info", f"Call job received — phone={phone_number} lead={lead_name} biz={business_name}")

    system_prompt = build_prompt(lead_name=lead_name, business_name=business_name,
                                  service_type=service_type, custom_prompt=custom_prompt)
    tool_ctx = AppointmentTools(ctx, phone_number, lead_name)

    if voice_override:
        os.environ["GEMINI_TTS_VOICE"] = voice_override
    if model_override:
        os.environ["GEMINI_MODEL"] = model_override

    if tools_override:
        try:
            enabled_tools = json.loads(tools_override)
        except Exception:
            enabled_tools = await get_enabled_tools()
    else:
        enabled_tools = await get_enabled_tools()

    # ── Connect ──────────────────────────────────────────────────────────────
    await ctx.connect()
    await _log("info", f"Connected to LiveKit room: {ctx.room.name}")

    # ── Dial — MUST come before session.start() ──────────────────────────────
    if phone_number:
        trunk_id = os.getenv("OUTBOUND_TRUNK_ID")
        if not trunk_id:
            await _log("error", "OUTBOUND_TRUNK_ID not set — cannot place outbound call")
            ctx.shutdown()
            return
        await _log("info", f"Dialing {phone_number} via SIP trunk {trunk_id}")
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=trunk_id,
                    sip_call_to=phone_number,
                    participant_identity=f"sip_{phone_number}",
                    wait_until_answered=True,
                )
            )
        except Exception as exc:
            await _log("error", f"SIP dial FAILED for {phone_number}: {exc}")
            ctx.shutdown()
            return
        await _log("info", f"Call ANSWERED — {phone_number} picked up, starting AI session now")

    # ── Build and start Gemini Live ──────────────────────────────────────────
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview")
    await _log("info", f"Building AI session — model={gemini_model}")
    active_tools = tool_ctx.build_tool_list(enabled_tools)
    await _log("info", f"Tools loaded: {[t.__name__ for t in active_tools]}")
    session = _build_session(tools=active_tools, system_prompt=system_prompt)

    # Use RoomOptions if available (non-deprecated), else fall back
    # NEVER use close_on_disconnect=True with SIP — drops on any audio blip
    if _HAS_ROOM_OPTIONS:
        from livekit.agents import RoomOptions as _RO
        _session_kwargs = dict(
            room=ctx.room,
            agent=OutboundAssistant(instructions=system_prompt),
            room_options=_RO(input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVCTelephony())),
        )
    else:
        _session_kwargs = dict(
            room=ctx.room,
            agent=OutboundAssistant(instructions=system_prompt),
            room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVCTelephony()),
        )

    await session.start(**_session_kwargs)
    await _log("info", "Agent session started — AI ready, generating greeting")

    # ── Optional S3 recording ────────────────────────────────────────────────
    if phone_number:
        _aws_key    = os.getenv("S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID", "")
        _aws_secret = os.getenv("S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY", "")
        _aws_bucket = os.getenv("S3_BUCKET") or os.getenv("AWS_BUCKET_NAME", "")
        _s3_endpoint = os.getenv("S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT", "")
        _s3_region  = os.getenv("S3_REGION") or os.getenv("AWS_REGION", "ap-northeast-1")
        if _aws_key and _aws_secret and _aws_bucket:
            try:
                _recording_path = f"recordings/{ctx.room.name}.ogg"
                _egress_req = api.RoomCompositeEgressRequest(
                    room_name=ctx.room.name, audio_only=True,
                    file_outputs=[api.EncodedFileOutput(
                        file_type=api.EncodedFileType.OGG, filepath=_recording_path,
                        s3=api.S3Upload(access_key=_aws_key, secret=_aws_secret,
                                        bucket=_aws_bucket, region=_s3_region, endpoint=_s3_endpoint),
                    )],
                )
                _egress = await ctx.api.egress.start_room_composite_egress(_egress_req)
                _s3_ep = _s3_endpoint.rstrip("/")
                tool_ctx.recording_url = (f"{_s3_ep}/{_aws_bucket}/{_recording_path}"
                                           if _s3_ep else f"s3://{_aws_bucket}/{_recording_path}")
                await _log("info", f"Recording started: egress={_egress.egress_id}")
            except Exception as _exc:
                await _log("warning", f"Recording start failed (non-fatal): {_exc}")

    # ── Greeting ─────────────────────────────────────────────────────────────
    # gemini-3.1 and gemini-2.5 native-audio speak autonomously from system prompt.
    # generate_reply() is blocked by the plugin for these models — skip it entirely.
    _active_model = os.getenv("GEMINI_MODEL", "")
    if "3.1" in _active_model or "2.5" in _active_model:
        await _log("info", "Gemini native-audio: model will greet autonomously from system prompt")
    else:
        greeting = (
            f"The call just connected. Greet the lead and ask if you're speaking with {lead_name}."
            if phone_number else "Greet the caller warmly."
        )
        try:
            await session.generate_reply(instructions=greeting)
        except Exception as _gr_exc:
            await _log("warning", f"generate_reply failed: {_gr_exc}")

    # ── Keep session alive until SIP participant actually leaves ─────────────
    # Without this block, the entrypoint returns and the process spins down.
    # We watch participant_disconnected for the specific SIP identity.
    if phone_number:
        _sip_identity = f"sip_{phone_number}"
        _disconnect_event = asyncio.Event()

        def _on_participant_disconnected(participant: rtc.RemoteParticipant):
            if participant.identity == _sip_identity:
                _disconnect_event.set()
        def _on_disconnected():
            _disconnect_event.set()

        ctx.room.on("participant_disconnected", _on_participant_disconnected)
        ctx.room.on("disconnected", _on_disconnected)

        try:
            await asyncio.wait_for(_disconnect_event.wait(), timeout=3600)
        except asyncio.TimeoutError:
            await _log("warning", "Call reached 1-hour safety timeout — shutting down")

        await _log("info", f"SIP participant disconnected — ending session for {phone_number}")
        await session.aclose()
    else:
        _done = asyncio.Event()
        ctx.room.on("disconnected", lambda: _done.set())
        try:
            await asyncio.wait_for(_done.wait(), timeout=3600)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    init_db()
    load_db_settings_to_env()
    agents.cli.run_app(
        agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="outbound-caller")
    )
```

---

## 11. `server.py` — Complete

```python
"""FastAPI backend for the OutboundAI dashboard."""

import asyncio
import json
import logging
import os
import random
import ssl
import certifi
import aiohttp
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

_orig_ssl = ssl.create_default_context
def _certifi_ssl(purpose=ssl.Purpose.SERVER_AUTH, **kwargs):
    if not kwargs.get("cafile") and not kwargs.get("capath") and not kwargs.get("cadata"):
        kwargs["cafile"] = certifi.where()
    return _orig_ssl(purpose, **kwargs)
ssl.create_default_context = _certifi_ssl

from db import (
    SENSITIVE_KEYS, cancel_appointment, clear_errors, create_campaign, delete_campaign,
    get_all_appointments, get_all_calls, get_all_campaigns, get_all_settings,
    get_all_agent_profiles, get_agent_profile, create_agent_profile, update_agent_profile,
    delete_agent_profile, set_default_agent_profile, get_calls_by_phone, get_campaign,
    get_contacts, get_errors, get_logs, get_setting, get_stats, init_db, log_error,
    save_settings, set_setting, update_call_notes, update_campaign_run_stats, update_campaign_status,
    delete_campaign,
)
from prompts import DEFAULT_SYSTEM_PROMPT

load_dotenv(".env", override=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

init_db()

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    _scheduler = AsyncIOScheduler()
except ImportError:
    _scheduler = None
    logger.warning("APScheduler not installed — campaign scheduling disabled")

app = FastAPI(title="OutboundAI Dashboard", version="1.0.0")


@app.on_event("startup")
async def _startup():
    if _scheduler:
        _scheduler.start()
        await _reschedule_all_campaigns()


@app.on_event("shutdown")
async def _shutdown():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


async def eff(key: str) -> str:
    val = await get_setting(key, "")
    return val if val else os.getenv(key, "")


# ── Request models ────────────────────────────────────────────────────────────

class CallRequest(BaseModel):
    phone: str
    lead_name: str = "there"
    business_name: str = "our company"
    service_type: str = "our service"
    system_prompt: Optional[str] = None
    agent_profile_id: Optional[str] = None


class AgentProfileRequest(BaseModel):
    name: str
    voice: str = "Aoede"
    model: str = "gemini-3.1-flash-live-preview"
    system_prompt: Optional[str] = None
    enabled_tools: str = "[]"
    is_default: bool = False


class PromptRequest(BaseModel):
    prompt: str


class SettingsRequest(BaseModel):
    settings: dict


class NotesRequest(BaseModel):
    notes: str


class CampaignRequest(BaseModel):
    name: str
    contacts: list
    schedule_type: str = "once"
    schedule_time: str = "09:00"
    call_delay_seconds: int = 3
    system_prompt: Optional[str] = None
    agent_profile_id: Optional[str] = None


class StatusRequest(BaseModel):
    status: str


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = Path(__file__).parent / "ui" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found — place index.html in ui/</h1>", status_code=404)


# ── Call dispatch ─────────────────────────────────────────────────────────────

@app.post("/api/call")
async def api_dispatch_call(req: CallRequest):
    url    = await eff("LIVEKIT_URL")
    key    = await eff("LIVEKIT_API_KEY")
    secret = await eff("LIVEKIT_API_SECRET")

    if not all([url, key, secret]):
        raise HTTPException(400, "LiveKit credentials not configured. Go to Settings → LiveKit.")

    phone = req.phone.strip()
    if not phone.startswith("+"):
        raise HTTPException(400, "Phone must be in E.164 format: +919876543210")

    effective_prompt = req.system_prompt
    effective_voice = None
    effective_model = None
    effective_tools = None

    if req.agent_profile_id:
        profile = await get_agent_profile(req.agent_profile_id)
        if profile:
            if not effective_prompt and profile.get("system_prompt"):
                effective_prompt = profile["system_prompt"]
            effective_voice = profile.get("voice")
            effective_model = profile.get("model")
            effective_tools = profile.get("enabled_tools")

    if not effective_prompt:
        effective_prompt = await get_setting("system_prompt", "") or None

    room_name = f"call-{phone.replace('+', '')}-{random.randint(1000, 9999)}"
    metadata: dict = {
        "phone_number": phone,
        "lead_name": req.lead_name,
        "business_name": req.business_name,
        "service_type": req.service_type,
        "system_prompt": effective_prompt,
    }
    if effective_voice:  metadata["voice_override"] = effective_voice
    if effective_model:  metadata["model_override"] = effective_model
    if effective_tools:  metadata["tools_override"] = effective_tools

    try:
        from livekit import api as lk_api
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx))
        lk = lk_api.LiveKitAPI(url=url, api_key=key, api_secret=secret, session=session)
        await lk.room.create_room(lk_api.CreateRoomRequest(name=room_name, empty_timeout=300, max_participants=5))
        await lk.agent_dispatch.create_dispatch(
            lk_api.CreateAgentDispatchRequest(
                agent_name="outbound-caller", room=room_name, metadata=json.dumps(metadata)
            )
        )
        await lk.aclose()
        await session.close()
        await log_error("server", f"Call dispatched to {phone}", f"room={room_name}", "info")
        return {"status": "dispatched", "room": room_name, "phone": phone}
    except Exception as exc:
        logger.error("Dispatch error: %s", exc)
        raise HTTPException(500, f"Dispatch failed: {exc}")


# ── Calls ─────────────────────────────────────────────────────────────────────

@app.get("/api/calls")
async def api_get_calls(page: int = 1, limit: int = 20):
    return await get_all_calls(page=page, limit=limit)


@app.patch("/api/calls/{call_id}/notes")
async def api_update_notes(call_id: str, req: NotesRequest):
    ok = await update_call_notes(call_id, req.notes)
    if not ok:
        raise HTTPException(404, "Call not found")
    return {"status": "updated"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_get_stats():
    return await get_stats()


# ── Appointments ──────────────────────────────────────────────────────────────

@app.get("/api/appointments")
async def api_get_appointments(date: Optional[str] = None):
    return await get_all_appointments(date_filter=date)


@app.delete("/api/appointments/{appointment_id}")
async def api_cancel_appointment(appointment_id: str):
    ok = await cancel_appointment(appointment_id)
    if not ok:
        raise HTTPException(404, "Appointment not found or already cancelled")
    return {"status": "cancelled"}


# ── Prompt ────────────────────────────────────────────────────────────────────

@app.get("/api/prompt")
async def api_get_prompt():
    saved = await get_setting("system_prompt", "")
    return {"prompt": saved or DEFAULT_SYSTEM_PROMPT, "is_custom": bool(saved)}


@app.post("/api/prompt")
async def api_save_prompt(req: PromptRequest):
    await set_setting("system_prompt", req.prompt)
    return {"status": "saved"}


@app.delete("/api/prompt")
async def api_reset_prompt():
    await set_setting("system_prompt", "")
    return {"status": "reset", "prompt": DEFAULT_SYSTEM_PROMPT}


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def api_get_settings():
    return await get_all_settings()


@app.post("/api/settings")
async def api_save_settings(req: SettingsRequest):
    filtered = {k: v for k, v in req.settings.items() if v is not None and v != ""}
    await save_settings(filtered)
    for k, v in filtered.items():
        os.environ[k] = str(v)
    return {"status": "saved", "count": len(filtered)}


# ── SIP trunk setup ───────────────────────────────────────────────────────────

@app.post("/api/setup/trunk")
async def api_setup_trunk():
    url    = await eff("LIVEKIT_URL")
    key    = await eff("LIVEKIT_API_KEY")
    secret = await eff("LIVEKIT_API_SECRET")
    sip_domain = await eff("VOBIZ_SIP_DOMAIN")
    username   = await eff("VOBIZ_USERNAME")
    password   = await eff("VOBIZ_PASSWORD")
    phone      = await eff("VOBIZ_OUTBOUND_NUMBER")

    if not all([url, key, secret, sip_domain, username, password, phone]):
        raise HTTPException(400, "Configure LiveKit and Vobiz credentials in Settings first.")

    try:
        from livekit import api as lk_api
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx))
        lk = lk_api.LiveKitAPI(url=url, api_key=key, api_secret=secret, session=session)
        trunk = await lk.sip.create_sip_outbound_trunk(
            lk_api.CreateSIPOutboundTrunkRequest(
                trunk=lk_api.SIPOutboundTrunkInfo(
                    name="Vobiz Outbound Trunk",
                    address=sip_domain,
                    auth_username=username,
                    auth_password=password,
                    numbers=[phone],
                )
            )
        )
        trunk_id = trunk.sip_trunk_id
        await set_setting("OUTBOUND_TRUNK_ID", trunk_id)
        os.environ["OUTBOUND_TRUNK_ID"] = trunk_id
        await lk.aclose()
        await session.close()
        return {"status": "created", "trunk_id": trunk_id}
    except Exception as exc:
        raise HTTPException(500, f"Trunk creation failed: {exc}")


# ── Logs ──────────────────────────────────────────────────────────────────────

@app.get("/api/logs")
async def api_get_logs(limit: int = 200, level: Optional[str] = None, source: Optional[str] = None):
    return await get_logs(level=level, source=source, limit=limit)


@app.delete("/api/logs")
async def api_clear_logs():
    await clear_errors()
    return {"status": "cleared"}


# ── CRM ───────────────────────────────────────────────────────────────────────

@app.get("/api/crm")
async def api_get_contacts():
    return {"data": await get_contacts()}


@app.get("/api/crm/calls")
async def api_get_contact_calls(phone: str = Query(...)):
    return {"data": await get_calls_by_phone(phone)}


# ── Agent Profiles ────────────────────────────────────────────────────────────

@app.get("/api/agent-profiles")
async def api_list_agent_profiles():
    try:
        return await get_all_agent_profiles()
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/agent-profiles")
async def api_create_agent_profile(req: AgentProfileRequest):
    try:
        profile_id = await create_agent_profile(
            name=req.name, voice=req.voice, model=req.model,
            system_prompt=req.system_prompt, enabled_tools=req.enabled_tools, is_default=req.is_default,
        )
        return {"status": "created", "id": profile_id}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/agent-profiles/{profile_id}")
async def api_get_agent_profile(profile_id: str):
    profile = await get_agent_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    return profile


@app.put("/api/agent-profiles/{profile_id}")
async def api_update_agent_profile(profile_id: str, req: AgentProfileRequest):
    ok = await update_agent_profile(profile_id, {
        "name": req.name, "voice": req.voice, "model": req.model,
        "system_prompt": req.system_prompt, "enabled_tools": req.enabled_tools,
        "is_default": 1 if req.is_default else 0,
    })
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"status": "updated"}


@app.delete("/api/agent-profiles/{profile_id}")
async def api_delete_agent_profile(profile_id: str):
    ok = await delete_agent_profile(profile_id)
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"status": "deleted"}


@app.post("/api/agent-profiles/{profile_id}/set-default")
async def api_set_default_profile(profile_id: str):
    try:
        await set_default_agent_profile(profile_id)
        return {"status": "default set"}
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Campaigns ─────────────────────────────────────────────────────────────────

async def _dispatch_one(lk, lk_api, contact: dict, room_name: str,
                         prompt: Optional[str], profile: Optional[dict] = None) -> bool:
    try:
        saved_prompt = prompt or (await get_setting("system_prompt", "")) or None
        metadata: dict = {
            "phone_number": contact["phone"],
            "lead_name": contact.get("lead_name", "there"),
            "business_name": contact.get("business_name", "our company"),
            "service_type": contact.get("service_type", "our service"),
            "system_prompt": saved_prompt,
        }
        if profile:
            if not metadata["system_prompt"] and profile.get("system_prompt"):
                metadata["system_prompt"] = profile["system_prompt"]
            if profile.get("voice"):   metadata["voice_override"] = profile["voice"]
            if profile.get("model"):   metadata["model_override"] = profile["model"]
            if profile.get("enabled_tools"): metadata["tools_override"] = profile["enabled_tools"]
        await lk.agent_dispatch.create_dispatch(
            lk_api.CreateAgentDispatchRequest(agent_name="outbound-caller", room=room_name, metadata=json.dumps(metadata))
        )
        return True
    except Exception as exc:
        logger.error("Campaign dispatch error for %s: %s", contact.get("phone"), exc)
        return False


async def _run_campaign(campaign_id: str) -> None:
    campaign = await get_campaign(campaign_id)
    if not campaign:
        return
    contacts = json.loads(campaign.get("contacts_json") or "[]")
    if not contacts:
        return
    delay = int(campaign.get("call_delay_seconds") or 3)
    prompt = campaign.get("system_prompt")
    agent_profile_id = campaign.get("agent_profile_id")
    profile = None
    if agent_profile_id:
        profile = await get_agent_profile(agent_profile_id)

    url    = await eff("LIVEKIT_URL")
    key    = await eff("LIVEKIT_API_KEY")
    secret = await eff("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        logger.error("Campaign %s: LiveKit not configured", campaign_id)
        return

    from livekit import api as lk_api_module
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx))

    ok_count = fail_count = 0
    try:
        lk = lk_api_module.LiveKitAPI(url=url, api_key=key, api_secret=secret, session=session)
        for i, contact in enumerate(contacts):
            phone = contact.get("phone", "")
            if not phone.startswith("+"):
                fail_count += 1
                continue
            room_name = f"camp-{campaign_id[:8]}-{phone.replace('+','')}-{random.randint(100,999)}"
            success = await _dispatch_one(lk, lk_api_module, contact, room_name, prompt, profile)
            if success:
                ok_count += 1
            else:
                fail_count += 1
            if i < len(contacts) - 1:
                await asyncio.sleep(delay)
        await lk.aclose()
    except Exception as exc:
        logger.error("Campaign run error: %s", exc)
    finally:
        await session.close()

    await update_campaign_run_stats(campaign_id, ok_count, fail_count)
    logger.info("Campaign %s done — %d dispatched, %d failed", campaign_id, ok_count, fail_count)


async def _reschedule_all_campaigns() -> None:
    if not _scheduler:
        return
    try:
        campaigns = await get_all_campaigns()
        for c in campaigns:
            if c.get("status") == "active" and c.get("schedule_type") in ("daily", "weekdays"):
                _schedule_campaign(c["id"], c["schedule_type"], c.get("schedule_time", "09:00"))
    except Exception as exc:
        logger.warning("Could not reschedule campaigns: %s", exc)


def _schedule_campaign(campaign_id: str, schedule_type: str, schedule_time: str) -> None:
    if not _scheduler:
        return
    job_id = f"campaign_{campaign_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    try:
        hour, minute = map(int, schedule_time.split(":"))
    except (ValueError, AttributeError):
        hour, minute = 9, 0
    if schedule_type == "daily":
        trigger = CronTrigger(hour=hour, minute=minute)
    else:
        trigger = CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute)
    _scheduler.add_job(_run_campaign, trigger=trigger, args=[campaign_id], id=job_id, replace_existing=True)
    logger.info("Scheduled campaign %s (%s at %02d:%02d)", campaign_id, schedule_type, hour, minute)


@app.post("/api/campaigns")
async def api_create_campaign(req: CampaignRequest):
    if not req.contacts:
        raise HTTPException(400, "contacts list cannot be empty")
    if req.schedule_type not in ("once", "daily", "weekdays"):
        raise HTTPException(400, "schedule_type must be: once | daily | weekdays")

    campaign_id = await create_campaign(
        name=req.name, contacts_json=json.dumps(req.contacts),
        schedule_type=req.schedule_type, schedule_time=req.schedule_time,
        call_delay_seconds=req.call_delay_seconds, system_prompt=req.system_prompt,
        agent_profile_id=req.agent_profile_id,
    )
    campaign = await get_campaign(campaign_id)

    if req.schedule_type == "once":
        asyncio.create_task(_run_campaign(campaign_id))
    else:
        _schedule_campaign(campaign_id, req.schedule_type, req.schedule_time)

    return {"status": "created", "campaign_id": campaign_id, "campaign": campaign}


@app.get("/api/campaigns")
async def api_list_campaigns():
    return await get_all_campaigns()


@app.delete("/api/campaigns/{campaign_id}")
async def api_delete_campaign(campaign_id: str):
    ok = await delete_campaign(campaign_id)
    if not ok:
        raise HTTPException(404, "Campaign not found")
    job_id = f"campaign_{campaign_id}"
    if _scheduler and _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    return {"status": "deleted"}


@app.post("/api/campaigns/{campaign_id}/run")
async def api_run_campaign_now(campaign_id: str):
    campaign = await get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    asyncio.create_task(_run_campaign(campaign_id))
    return {"status": "dispatching", "campaign_id": campaign_id}


@app.patch("/api/campaigns/{campaign_id}/status")
async def api_update_campaign_status(campaign_id: str, req: StatusRequest):
    if req.status not in ("active", "paused", "completed"):
        raise HTTPException(400, "status must be: active | paused | completed")
    ok = await update_campaign_status(campaign_id, req.status)
    if not ok:
        raise HTTPException(404, "Campaign not found")
    job_id = f"campaign_{campaign_id}"
    if req.status == "paused" and _scheduler and _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    elif req.status == "active":
        campaign = await get_campaign(campaign_id)
        if campaign and campaign.get("schedule_type") in ("daily", "weekdays"):
            _schedule_campaign(campaign_id, campaign["schedule_type"], campaign.get("schedule_time", "09:00"))
    return {"status": req.status}
```

---

## 12. `ui/index.html` — Dashboard Structure

Build a **single-file HTML dashboard** with all CSS and JS inline. No external dependencies except Chart.js CDN.

### Head:
```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>OutboundAI — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
/* Dark theme CSS variables */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d0d0d; --card:#161616; --border:#252525;
  --accent:#00ff88; --accent2:#00ccff; --danger:#ff4d4d; --warn:#ffaa00;
  --muted:#5a5a5a; --text:#e0e0e0; --text2:#aaa;
  --mono:'Courier New',monospace; --sans:'Segoe UI',system-ui,sans-serif; --r:8px;
}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;line-height:1.5;font-size:14px}
/* Full CSS for header, nav tabs, cards, forms, buttons, tables, badges, charts, etc. */
</style>
</head>
```

### Navigation tabs (in order):
```
📊 Stats | 📞 Single Call | 📋 Batch Call | 🚀 Campaigns | 🤖 Agents |
✏️ AI Prompt | 📅 Appointments | 📝 Call Logs | 👥 CRM | ⚙️ Settings | 📋 Logs | 🔧 Setup
```

### Tab panels to implement:

**📊 Stats** — KPI grid (Total Calls, Booked, Not Interested, Booking Rate %, Avg Duration), Live Config chips, 3 Chart.js charts (outcomes donut, 14-day timeline line, avg duration by outcome bar)

**📞 Single Call** — Form: phone (E.164), lead name, business name, service type, agent profile dropdown (populated from API), optional custom prompt textarea (hidden behind checkbox), Submit button

**📋 Batch Call** — Agent profile dropdown, CSV file input, delay input, Parse CSV button (shows preview table), Start Batch button with progress bar

**🚀 Campaigns** — Create form: name, schedule (once/daily/weekdays), time picker, delay, agent profile dropdown, custom prompt checkbox, CSV file + parse. Campaign list table with run/pause/delete actions.

**🤖 Agents** — Create/edit form: profile name, voice select (30 voices grouped by gender), model select, enabled tools input, system prompt textarea, is_default checkbox. Profiles table with Edit/★ Default/Delete actions.

**✏️ AI Prompt** — Large textarea for global system prompt, Save/Reset buttons, character count.

**📅 Appointments** — Date filter, appointments table with Cancel button per row.

**📝 Call Logs** — Paginated table: phone, lead, outcome badge, duration, timestamp, recording link, inline notes editor.

**👥 CRM** — Contacts table aggregated by phone. Click row → drill-down to full call history + notes.

**⚙️ Settings** — BYOK groups: LiveKit, Gemini (model + voice + mode), Vobiz SIP + SIP trunk creation button, Twilio SMS, S3 Recordings, Cal.com, Tool Toggles. Each group has Save button. Sensitive fields have eye-toggle show/hide.

**📋 Logs** — Auto-refreshing log viewer with level filter (all/info/warning/error), source filter, Clear button, pause/resume auto-refresh.

**🔧 Setup** — Quick-start guide, cost breakdown card.

### JavaScript functions to implement:

```javascript
// Core utilities
const $ = id => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then(r => r.json());
const apiPost = (path, body) => fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
const apiDel  = path => fetch(path, {method:'DELETE'});
function toast(msg, type='ok') { /* show floating notification */ }
function showErr(id, msg) { /* show inline error */ }
function switchTab(name) { /* switch active tab + panel, load relevant data */ }

// Stats + Charts
async function loadStats() { /* fetch /api/stats, update KPIs, render 3 charts */ }
async function loadLiveConfig() { /* fetch /api/settings + /api/prompt, update Live Config chips */ }
function _mkChart(id, type, data, options) { /* create/update Chart.js instance */ }
function _renderCharts(d) { /* outcomes donut, timeline line, duration bar */ }

// Single Call
// submit handler on #call-form → POST /api/call with agent_profile_id

// Batch Call
// parse CSV → dispatch loop with delay → progress bar

// Campaigns
async function loadCampaigns() { /* GET /api/campaigns, render table */ }
async function createCampaign() { /* POST /api/campaigns */ }
window.runCampaign = async (id, name) => { /* POST /api/campaigns/{id}/run */ }
window.toggleCampaignStatus = async (id, newStatus) => { /* PATCH /api/campaigns/{id}/status */ }
window.deleteCampaign = async (id, name) => { /* DELETE /api/campaigns/{id} */ }

// Agent Profiles
async function loadAgentProfiles() {
  const raw = await api('/api/agent-profiles');
  const profiles = Array.isArray(raw) ? raw : []; // guard against non-array (table not yet created)
  // render table, populate all 3 dropdowns: f-agent-profile, bc-agent-profile, camp-agent-profile
}
window.saveAgentProfile = async () => { /* POST or PUT /api/agent-profiles */ }
window.editAgentProfile = async (id) => { /* GET /api/agent-profiles/{id}, fill form */ }
window.deleteAgentProfile = async (id, name) => { /* DELETE */ }
window.setDefaultAgentProfile = async (id, name) => { /* POST /api/agent-profiles/{id}/set-default */ }
window.resetAgentForm = () => { /* clear form */ }

// Prompt
async function loadPrompt() { /* GET /api/prompt */ }
window.savePrompt = async () => { /* POST /api/prompt */ }
window.resetPrompt = async () => { /* DELETE /api/prompt */ }

// Appointments
async function loadAppointments() { /* GET /api/appointments */ }
window.cancelAppointment = async (id) => { /* DELETE /api/appointments/{id} */ }

// Call Logs (paginated)
async function loadCalls(page=1) { /* GET /api/calls?page=X&limit=20 */ }
window.saveNotes = async (callId) => { /* PATCH /api/calls/{id}/notes */ }

// CRM
async function loadCRM() { /* GET /api/crm */ }
window.loadContactDetail = async (phone) => { /* GET /api/crm/calls?phone=X */ }

// Settings
async function loadSettings() { /* GET /api/settings, fill all fields + show configured badges */ }
async function saveGroup(group) { /* POST /api/settings with group fields */ }
window.createSIPTrunk = async () => { /* POST /api/setup/trunk */ }
window.saveToolToggles = async () => { /* POST /api/settings with ENABLED_TOOLS JSON */ }

// Logs
async function loadLogs() { /* GET /api/logs with filters */ }
function scheduleLogsRefresh() { /* 5s interval with pause/resume */ }

// Init
function init() {
  loadStats();
  loadCalls();
  loadAppointments();
  loadLogs();
  loadAgentProfiles(); // populates all dropdowns
  setInterval(loadStats, 10000);
  scheduleLogsRefresh();
}
document.addEventListener('DOMContentLoaded', init);
```

### Voice select options (use in both Settings tab and Agent Profile form):

```html
<optgroup label="Female voices">
  <option value="Aoede">Aoede — warm, expressive ⭐</option>
  <option value="Achernar">Achernar — soft & clear</option>
  <option value="Autonoe">Autonoe — natural female</option>
  <option value="Callirrhoe">Callirrhoe — gentle female</option>
  <option value="Despina">Despina — bright female</option>
  <option value="Erinome">Erinome — smooth female</option>
  <option value="Gacrux">Gacrux — rich female</option>
  <option value="Kore">Kore — soft, calm</option>
  <option value="Laomedeia">Laomedeia — light female</option>
  <option value="Leda">Leda — clear female</option>
  <option value="Pulcherrima">Pulcherrima — warm female</option>
  <option value="Sulafat">Sulafat — smooth female</option>
  <option value="Vindemiatrix">Vindemiatrix — professional female</option>
  <option value="Zephyr">Zephyr — airy female</option>
</optgroup>
<optgroup label="Male voices">
  <option value="Achird">Achird — clear male</option>
  <option value="Algenib">Algenib — strong male</option>
  <option value="Algieba">Algieba — rich male</option>
  <option value="Alnilam">Alnilam — deep male</option>
  <option value="Charon">Charon — calm, deep</option>
  <option value="Enceladus">Enceladus — expressive male</option>
  <option value="Fenrir">Fenrir — confident male</option>
  <option value="Iapetus">Iapetus — steady male</option>
  <option value="Orus">Orus — warm male</option>
  <option value="Perseus">Perseus — clear male</option>
  <option value="Puck">Puck — bright, energetic</option>
  <option value="Rasalgethi">Rasalgethi — bold male</option>
  <option value="Sadachbia">Sadachbia — natural male</option>
  <option value="Sadaltager">Sadaltager — smooth male</option>
  <option value="Schedar">Schedar — professional male</option>
  <option value="Umbriel">Umbriel — deep, calm</option>
  <option value="Zubenelgenubi">Zubenelgenubi — resonant male</option>
</optgroup>
```

---

## 13. Critical Architecture Rules (DO NOT DEVIATE)

### Rule 1: Dial-First Pattern

```python
# CORRECT — session starts AFTER call is answered
await ctx.api.sip.create_sip_participant(..., wait_until_answered=True)
# call is now answered ↑
session = _build_session(...)
await session.start(...)

# WRONG — session starts before dialing (will timeout during ring)
session = _build_session(...)
await session.start(...)
await ctx.api.sip.create_sip_participant(...)
```

### Rule 2: Never use `close_on_disconnect=True` with SIP

```python
# WRONG — kills session on any brief SIP audio dropout
room_input_options=RoomInputOptions(close_on_disconnect=True)

# CORRECT — watch participant_disconnected event manually
_disconnect_event = asyncio.Event()
def _on_disconnect(participant):
    if participant.identity == f"sip_{phone_number}":
        _disconnect_event.set()
ctx.room.on("participant_disconnected", _on_disconnect)
await asyncio.wait_for(_disconnect_event.wait(), timeout=3600)
```

### Rule 3: EndSensitivity enum — exact string required

```python
# WRONG — AttributeError, silently skips all 3 silence-prevention configs
end_of_speech_sensitivity=_gt.EndSensitivity.LOW

# CORRECT
end_of_speech_sensitivity=_gt.EndSensitivity.END_SENSITIVITY_LOW
```

### Rule 4: Gemini 3.1 and 2.5 speak autonomously

`generate_reply()` is **blocked** by the livekit-plugins-google plugin for `gemini-3.1-*` and `gemini-2.5-*` native audio models. Calling it raises an error. These models speak automatically from the system prompt when audio starts flowing. The system prompt must instruct the model to speak first.

```python
# CORRECT — check model name before calling generate_reply
if "3.1" in model or "2.5" in model:
    pass  # model speaks autonomously
else:
    await session.generate_reply(instructions="Greet the caller...")
```

### Rule 5: Model availability

| Model | Works? | Notes |
|---|---|---|
| `gemini-3.1-flash-live-preview` | ✅ YES | Recommended. Free tier. v1alpha API. |
| `gemini-2.5-flash-native-audio-preview-12-2025` | ✅ YES | Alternative |
| `gemini-2.0-flash-live-001` | ❌ NO | 1008 policy error on standard API keys |
| `gemini-3.1-flash-lite-preview` | ❌ NO | No bidiGenerateContent support |
| Any `-lite` model | ❌ NO | Lite models don't support Gemini Live |

### Rule 6: All 3 silence-prevention configs are mandatory

```python
from google.genai import types as _gt

# 1. Transparent session resumption — auto-reconnects on timeout instead of going silent
session_resumption=_gt.SessionResumptionConfig(transparent=True)

# 2. Context window compression — prevents freeze when context fills up
context_window_compression=_gt.ContextWindowCompressionConfig(
    trigger_tokens=25600,
    sliding_window=_gt.SlidingWindow(target_tokens=12800),
)

# 3. VAD tuning — 2 second silence threshold, low sensitivity
realtime_input_config=_gt.RealtimeInputConfig(
    automatic_activity_detection=_gt.AutomaticActivityDetection(
        end_of_speech_sensitivity=_gt.EndSensitivity.END_SENSITIVITY_LOW,
        silence_duration_ms=2000,
        prefix_padding_ms=200,
    ),
)
```

Without all 3, calls will go silent within 30–90 seconds.

### Rule 7: Never hardcode credentials in source code

```python
# WRONG
LIVEKIT_API_KEY = "APIxxxxxxxxx"
SUPABASE_SERVICE_KEY = "eyJhbGci..."

# CORRECT — always load from environment
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
```

### Rule 8: FastAPI server always runs on port 8000

LiveKit agent worker occupies port 8081 internally. Never run uvicorn on 8081.

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
python agent.py start  # uses port 8081 internally
```

### Rule 9: Settings priority order

1. Coolify / Docker env vars (set at container startup)
2. Supabase `settings` table (set via dashboard Settings tab)
3. Values in `db.py` DEFAULTS (empty strings — never real credentials)

DB settings override env vars at runtime via `get_setting()` → `_default()` fallback chain.

### Rule 10: Agent profile override flow

When a call or campaign has an `agent_profile_id`:
1. Load profile from `agent_profiles` table
2. Set `voice_override`, `model_override`, `tools_override` in dispatch metadata
3. Agent reads overrides from metadata and sets `os.environ["GEMINI_TTS_VOICE"]` etc. before building session

---

## 14. Deployment on Coolify

1. **VPS** — Any Linux VPS, minimum 2GB RAM, 2 vCPU. Hetzner CX21 (€3.79/mo) works.
2. **Install Coolify** — `curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash`
3. **New Resource** → GitHub → select repo → Dockerfile detected automatically
4. **Set all environment variables** (from Section 2)
5. **Set port to 8000**
6. **Deploy**
7. After first deploy: open dashboard URL → Settings → fill in API keys → click ⚡ Create SIP Trunk

### Successful startup log output:
```
🚀 Starting Outbound Mass Caller...
✅ Supabase connected
🌐 Starting FastAPI server on port 8000...
🤖 Starting LiveKit agent worker...
{"message": "registered worker", "agent_name": "outbound-caller", ...}
```

---

## 15. Known Gotchas Table

| Symptom | Root Cause | Fix |
|---|---|---|
| Call drops exactly at 60s | `close_on_disconnect=True` fires on SIP audio dropout | Remove it; use `participant_disconnected` event instead |
| Agent goes silent after 30–90s | `EndSensitivity.LOW` causes AttributeError, all 3 silence configs skip silently | Use `EndSensitivity.END_SENSITIVITY_LOW` (full string) |
| No initial greeting | Using 3.1/2.5 model but calling `generate_reply()` | These models speak autonomously — skip `generate_reply()` |
| 1008 error on session start | Using `gemini-2.0-flash-live-001` on standard API key | Switch to `gemini-3.1-flash-live-preview` |
| `AgentSession isn't running` | Session started before SIP call answered | Dial-first: `wait_until_answered=True` before `session.start()` |
| Port 8081 in use | Old agent worker still running | `pkill -9 -f "agent.py start"` |
| `profiles.map is not a function` | `agent_profiles` table doesn't exist in Supabase | Run `supabase_schema.sql` in Supabase SQL Editor |
| Worker uses old model after Settings change | `load_db_settings_to_env()` only runs at startup | Redeploy after changing model in Settings |
| `DefaultCredentialsError` on TTS | Using `google.TTS` (needs ADC) with Gemini Live models | Don't attach TTS to realtime models — it's built in |
| Duplicate tool name error | Passing tools to both `super().__init__()` and `AgentSession` | Pass `tools=[]` to Agent `super().__init__()`, only to `AgentSession` |
| `SSL certificate verify failed` | Missing certifi CA bundle | Patch `ssl.create_default_context` with certifi at top of agent.py and server.py |
| Campaigns table not found | Schema not run on deployed Supabase | Run full `supabase_schema.sql` in Supabase SQL Editor |

---

## 16. Available Gemini Live Voices (30 total)

These are the only voice names that work with the Gemini Live API. Use them exactly as shown.

**Female (14):** Aoede, Achernar, Autonoe, Callirrhoe, Despina, Erinome, Gacrux, Kore, Laomedeia, Leda, Pulcherrima, Sulafat, Vindemiatrix, Zephyr

**Male (16):** Achird, Algenib, Algieba, Alnilam, Charon, Enceladus, Fenrir, Iapetus, Orus, Perseus, Puck, Rasalgethi, Sadachbia, Sadaltager, Schedar, Umbriel, Zubenelgenubi

Default: **Aoede** (warm female, works well for appointment booking persona)

---

## 17. Cost Breakdown

| Service | Cost per minute | Notes |
|---|---|---|
| Vobiz SIP | ₹1.00/min | Fixed telephony cost |
| LiveKit Cloud | ₹0.17/min ($0.002) | Free tier: 100k participant-minutes/mo |
| Gemini Live | ₹0.03/min | Free tier covers most usage; ~$0.075/1M audio tokens |
| Deepgram STT | ₹0.58/min | Pipeline mode only — not used in default setup |
| **Total (realtime)** | **≈ ₹1.20/min** | Under ₹1.50 target |

A typical 2-minute call costs **≈ ₹2.40**.

---

## 18. API Integrations Reference

### LiveKit Agent Dispatch

```python
from livekit import api as lk_api

lk = lk_api.LiveKitAPI(url=LIVEKIT_URL, api_key=API_KEY, api_secret=API_SECRET, session=aiohttp_session)

# Create room
await lk.room.create_room(lk_api.CreateRoomRequest(name=room_name, empty_timeout=300, max_participants=5))

# Dispatch agent job
await lk.agent_dispatch.create_dispatch(
    lk_api.CreateAgentDispatchRequest(
        agent_name="outbound-caller",   # MUST match agents.WorkerOptions(agent_name=...)
        room=room_name,
        metadata=json.dumps({"phone_number": "+91...", "lead_name": "...", ...})
    )
)

# Outbound SIP dial (called from inside agent entrypoint, not server)
await ctx.api.sip.create_sip_participant(
    api.CreateSIPParticipantRequest(
        room_name=ctx.room.name,
        sip_trunk_id=OUTBOUND_TRUNK_ID,
        sip_call_to=phone_number,
        participant_identity=f"sip_{phone_number}",
        wait_until_answered=True,       # BLOCKS until answered — required for dial-first pattern
    )
)

# SIP REFER transfer
await ctx.api.sip.transfer_sip_participant(
    api.TransferSIPParticipantRequest(
        room_name=ctx.room.name,
        participant_identity=f"sip_{phone_number}",
        transfer_to=f"sip:{destination}@{sip_domain}",
        play_dialtone=False,
    )
)
```

### Cal.com API v1

```python
import httpx

# Book
resp = await httpx.AsyncClient().post(
    "https://api.cal.com/v1/bookings",
    headers={"Authorization": f"Bearer {CALCOM_API_KEY}"},
    json={
        "eventTypeId": int(CALCOM_EVENT_TYPE_ID),
        "start": "2026-04-25T09:00:00.000Z",
        "timeZone": "Asia/Kolkata",
        "responses": {"name": "Shreyas Raj", "email": "test@test.com"},
        "metadata": {"source": "OutboundAI"},
    }
)
uid = resp.json()["uid"]

# Cancel
await httpx.AsyncClient().delete(f"https://api.cal.com/v1/bookings/{uid}",
    headers={"Authorization": f"Bearer {CALCOM_API_KEY}"})
```

### Supabase (async)

```python
from supabase._async.client import create_client

db = await create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Insert
await db.table("call_logs").insert({...}).execute()

# Select
result = await db.table("appointments").select("*").eq("date", "2026-04-25").execute()
rows = result.data or []

# Upsert (insert or update by primary key)
await db.table("settings").upsert({"key": "GEMINI_MODEL", "value": "...", "updated_at": "..."}, on_conflict="key").execute()

# Update
await db.table("appointments").update({"status": "cancelled"}).eq("id", appointment_id).execute()

# Delete
await db.table("contact_memory").delete().eq("phone_number", phone).execute()
```

---

## 19. One-Time Setup Sequence

After deploying for the first time:

1. Open dashboard URL
2. Go to **SQL Editor** in Supabase → run `supabase_schema.sql`
3. Go to **⚙️ Settings** → fill in:
   - LiveKit URL, API Key, API Secret → Save
   - Google Gemini API Key, select Model, Voice → Save
   - Vobiz SIP Domain, Username, Password, Outbound Number → Save → click **⚡ Create SIP Trunk in LiveKit**
4. Go to **✏️ AI Prompt** → customise the prompt for your business name / service type → Save
5. Go to **🤖 Agents** → create at least one agent profile (give it a name and your business info in the prompt)
6. Go to **📞 Single Call** → test with your own number
7. Hear the AI speak within 5–10 seconds of the call connecting ✅

---

*This specification is complete. Build every file exactly as shown. Every function, every import, every config option matters.*
