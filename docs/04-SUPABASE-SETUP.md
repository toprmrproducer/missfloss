# 🗄️ Supabase Setup

Run this **once** to create all the database tables the app needs.

---

## How to run the schema

1. Go to [supabase.com](https://supabase.com) → your project
2. Click **SQL Editor** in the left sidebar
3. Click **+ New query**
4. Paste the entire SQL below
5. Click **Run** (or press `Ctrl+Enter` / `Cmd+Enter`)
6. You should see: `Success. No rows returned`

---

## Full schema SQL

```sql
-- ═══════════════════════════════════════════════════
-- OutboundAI — Complete Database Schema
-- Safe to run multiple times (uses IF NOT EXISTS)
-- ═══════════════════════════════════════════════════

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

-- Disable RLS so the service_role key can read/write freely
ALTER TABLE appointments  DISABLE ROW LEVEL SECURITY;
ALTER TABLE call_logs     DISABLE ROW LEVEL SECURITY;
ALTER TABLE settings      DISABLE ROW LEVEL SECURITY;
ALTER TABLE error_logs    DISABLE ROW LEVEL SECURITY;

-- Add recording and notes columns to call logs
ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS recording_url TEXT;
ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS notes TEXT;

-- Campaigns table — mass calling with scheduling
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

-- Cal.com booking tracking
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS calcom_booking_uid TEXT;

-- Contact memory — AI-extracted key insights per person
CREATE TABLE IF NOT EXISTS contact_memory (
    id TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL,
    insight TEXT NOT NULL,
    created_at TEXT NOT NULL
);
ALTER TABLE contact_memory DISABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_contact_memory_phone ON contact_memory (phone_number);

-- Agent profile column on campaigns
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

-- Agent profiles — named reusable agent configurations
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

## What each table does

| Table | Purpose |
|---|---|
| `appointments` | Stores every appointment the AI books |
| `call_logs` | Every call — outcome, duration, recording URL, notes |
| `settings` | All API keys and config saved from the dashboard Settings tab |
| `error_logs` | Application errors — visible in the Logs tab |
| `campaigns` | Mass calling campaigns with scheduling |
| `contact_memory` | AI-extracted notes about each lead, keyed by phone number |
| `agent_profiles` | Named agent configs (voice, model, prompt, tools) |

---

## Troubleshooting

**`relation "campaigns" does not exist`**
→ You haven't run the schema yet, or it errored partway through. Run the full SQL again — it's safe to re-run.

**`ERROR: column already exists`**
→ Ignore it — the `ADD COLUMN IF NOT EXISTS` syntax prevents this but older Postgres versions may show a warning. The schema still applied correctly.

**`permission denied`**
→ You're using the `anon` key instead of the `service_role` key. Go to Project Settings → API → copy the **service_role** secret key.
