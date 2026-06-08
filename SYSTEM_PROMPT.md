# Outbound Mass Caller — Complete System Specification

> Drop this file into any AI coding assistant and say: **"Build this exactly."**
> Every architectural decision, gotcha, and production fix is captured below.

---

## 0. What This System Is

A **production-grade AI outbound voice calling platform** that:

- Dials phone numbers automatically via SIP telephony (Vobiz)
- Connects calls to a **Gemini Live realtime AI voice agent** (sub-100ms latency)
- Books appointments into Supabase DB and optionally into **Cal.com**
- Runs mass **campaign calling** with APScheduler (once / daily / weekdays at time)
- Maintains a **CRM** with per-contact call history, editable notes, AI-extracted memory
- Remembers key details about each lead across calls using Gemini Flash auto-compression
- Records calls to S3 / Supabase Storage via LiveKit Egress
- Full-stack dashboard: single call, batch CSV, campaigns, AI prompt editor, appointments, call logs, CRM, settings (BYOK), live logs
- Persists everything to **Supabase** (zero local SQLite)

**Active model:** `gemini-3.1-flash-live-preview` — best quality, connects reliably on v1alpha API  
**Cost:** ≈ ₹1.21/min total (Vobiz ₹1.00 + LiveKit ₹0.17 + Gemini ₹0.03/min)  
**Stack:** Python 3.14 · LiveKit Agents 1.x · Gemini Live · Vobiz SIP · FastAPI · Supabase · APScheduler · Cal.com API v1 · vanilla HTML/JS dashboard

---

## 1. Repository File Structure

```
/
├── agent.py              # LiveKit worker — voice AI entrypoint
├── server.py             # FastAPI backend — all REST endpoints + APScheduler
├── db.py                 # All Supabase async DB operations + DEFAULTS dict
├── tools.py              # LLM function tools (9 total — see Section 8)
├── prompts.py            # System prompt template + build_prompt()
├── start.sh              # Production startup: uvicorn (port 8000) + agent worker
├── Dockerfile            # CMD: sh start.sh
├── requirements.txt      # Python dependencies
├── supabase_schema.sql   # Run once in Supabase SQL Editor
├── .env                  # Secrets — never commit, always .gitignore
├── .gitignore
└── ui/
    └── index.html        # Single-file dashboard (all CSS + JS inline)
```

---

## 2. Environment Variables (`.env`)

```env
# LiveKit Cloud — cloud.livekit.io → Project → Keys
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Google Gemini — aistudio.google.com/app/apikey
GOOGLE_API_KEY=AIzaSy...

# Model — gemini-2.0-flash-live-001 is cheapest stable Live model
# Lite models (gemini-3.1-flash-lite-preview etc.) do NOT support bidiGenerateContent
# and cannot be used for Live audio sessions.
GEMINI_MODEL=gemini-2.0-flash-live-001
GEMINI_TTS_VOICE=Aoede
USE_GEMINI_REALTIME=true

# Vobiz SIP — console.vobiz.ai
VOBIZ_SIP_DOMAIN=xxxxxxxx.sip.vobiz.ai
VOBIZ_USERNAME=your_username
VOBIZ_PASSWORD=your_password
VOBIZ_OUTBOUND_NUMBER=+91XXXXXXXXXX
OUTBOUND_TRUNK_ID=          # auto-filled by /api/setup/trunk
DEFAULT_TRANSFER_NUMBER=+91XXXXXXXXXX   # SIP REFER target for human transfer

# Deepgram — deepgram.com (pipeline STT fallback + Gemini 3.1 greeting TTS)
DEEPGRAM_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Twilio SMS — optional, leave blank to skip
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=

# FastAPI
HOST=0.0.0.0
PORT=8000

# Supabase — supabase.com → Project Settings → API
SUPABASE_URL=https://xxxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...

# S3 / Supabase Storage — for call recordings (optional)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_BUCKET_NAME=
AWS_REGION=us-east-1
S3_ENDPOINT=          # For Supabase Storage: https://<ref>.supabase.co/storage/v1/s3

# Cal.com — cal.com/settings/developer/api-keys (optional)
CALCOM_API_KEY=cal_live_...
CALCOM_EVENT_TYPE_ID=123456   # number in your event URL
CALCOM_TIMEZONE=Asia/Kolkata

# Tool toggles — JSON array of enabled tool names; empty = all enabled
ENABLED_TOOLS=
```

All settings can also be managed from the **Settings tab** in the dashboard (BYOK). DB-saved values override `.env`.

---

## 3. Supabase Schema

Run **once** in Supabase Dashboard → SQL Editor. Full file: `supabase_schema.sql`.

```sql
CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL, phone TEXT NOT NULL,
    date TEXT NOT NULL, time TEXT NOT NULL, service TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'booked',
    calcom_booking_uid TEXT,    -- Cal.com UID if calendar sync enabled
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_logs (
    id TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL, lead_name TEXT,
    outcome TEXT,               -- booked|not_interested|voicemail|wrong_number|callback_requested
    reason TEXT, duration_seconds INTEGER,
    recording_url TEXT,         -- S3/Supabase Storage URL
    notes TEXT,                 -- editable CRM notes
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active|paused|completed
    contacts_json TEXT NOT NULL DEFAULT '[]',
    schedule_type TEXT NOT NULL DEFAULT 'once',  -- once|daily|weekdays
    schedule_time TEXT DEFAULT '09:00',
    call_delay_seconds INTEGER DEFAULT 3,
    system_prompt TEXT,
    created_at TEXT NOT NULL, last_run_at TEXT,
    total_dispatched INTEGER DEFAULT 0, total_failed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contact_memory (
    id TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL,
    insight TEXT NOT NULL,      -- AI-extracted key detail about the lead
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS error_logs (
    id TEXT PRIMARY KEY, source TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL, detail TEXT, timestamp TEXT NOT NULL
);

-- Disable RLS so service_role key reads/writes freely
ALTER TABLE appointments   DISABLE ROW LEVEL SECURITY;
ALTER TABLE call_logs      DISABLE ROW LEVEL SECURITY;
ALTER TABLE campaigns      DISABLE ROW LEVEL SECURITY;
ALTER TABLE contact_memory DISABLE ROW LEVEL SECURITY;
ALTER TABLE settings       DISABLE ROW LEVEL SECURITY;
ALTER TABLE error_logs     DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_contact_memory_phone ON contact_memory (phone_number);
```

---

## 4. Critical Architecture: Dial-First Pattern

**THE most important rule.** Gemini Live WebSocket has a short idle timeout (~3 min). If you start the session before the SIP call is answered (ring time ≈ 20–30 s), the session times out during ring → goes silent immediately on pickup.

```python
# CORRECT order in entrypoint():
await ctx.connect()
await ctx.api.sip.create_sip_participant(
    ..., wait_until_answered=True   # ← BLOCKS until call is answered
)
# Only now build and start the Gemini Live session
session = _build_session(tools=active_tools, system_prompt=system_prompt)
await session.start(room=ctx.room, agent=..., room_input_options=...)
```

**NEVER** call `session.start()` before `create_sip_participant()`.

---

## 5. Silence Prevention — `_build_session()` Config

Three configs prevent the "goes silent after 1–2 min" issue:

```python
from google.genai import types as gt

realtime_kwargs = dict(
    model=gemini_model,
    voice=gemini_voice,
    instructions=system_prompt,
    # 1. Auto-resume: session reconnects transparently after timeout instead of going silent
    session_resumption=gt.SessionResumptionConfig(transparent=True),
    # 2. Context compression: slides old turns out of context window instead of freezing
    context_window_compression=gt.ContextWindowCompressionConfig(
        trigger_tokens=25600,
        sliding_window=gt.SlidingWindow(target_tokens=12800),
    ),
    # 3. VAD tuning: less aggressive end-of-speech detection
    realtime_input_config=gt.RealtimeInputConfig(
        automatic_activity_detection=gt.AutomaticActivityDetection(
            # ⚠️ GOTCHA: use END_SENSITIVITY_LOW not .LOW — full string enum required
            end_of_speech_sensitivity=gt.EndSensitivity.END_SENSITIVITY_LOW,
            silence_duration_ms=2000,
            prefix_padding_ms=200,
        ),
    ),
)
```

Root causes the above fixes:
- **Context window full** → model freezes (fixed by `context_window_compression`)
- **Session timeout** → silent reconnect fail (fixed by `session_resumption transparent=True`)
- **VAD too aggressive** → model ends turn early, stops listening (fixed by `LOW` sensitivity + 2000ms silence threshold)

---

## 6. Gemini 3.1 Special Handling

`generate_reply()` is **silently ignored** for `gemini-3.1-*` models — the LiveKit plugin explicitly warns:  
`"generate_reply is not compatible with 'gemini-3.1-flash-live-preview' and will be ignored."`

**The 3.1 model speaks autonomously.** It listens to the audio stream and responds on its own without `generate_reply()`. The system prompt must instruct it to greet immediately on connect — the model picks up the call and speaks first based on its instructions.

```python
# Do NOT use session.say() with a separate TTS — that path fails silently on SIP legs.
# Do NOT use generate_reply() — it's a no-op for 3.1.
# Just write the system prompt to open the conversation immediately.
# The model speaks as soon as audio starts flowing.
try:
    await session.generate_reply(instructions="Greet the lead...")
except Exception as e:
    pass  # harmless for 3.1 — model speaks from system prompt anyway
```

**Model availability:** Only models with `bidiGenerateContent` in their supported methods work for Gemini Live. As of 2026-04:
- `gemini-3.1-flash-live-preview` → works on **v1alpha** API (default)
- `gemini-2.0-flash-live-001` → **NOT accessible** on v1alpha or v1beta for standard API keys
- No "lite" model supports `bidiGenerateContent`

---

## 7. Model Selection Guide

| Model | Supports Live | Cost | Notes |
|---|---|---|---|
| `gemini-3.1-flash-live-preview` | ✅ | Preview | **Recommended** — connects reliably on v1alpha; best voice quality |
| `gemini-2.5-flash-native-audio-preview-12-2025` | ✅ | Mid | Alternative 2.5 native audio model |
| `gemini-2.0-flash-live-001` | ⚠️ | Cheapest | GA model BUT inaccessible on standard API keys (1008 error on both v1alpha and v1beta) |
| `gemini-3.1-flash-lite-preview` | ❌ | — | Does NOT support Live WebSocket (`bidiGenerateContent`) |
| `gemini-2.5-flash-lite` | ❌ | — | Does NOT support Live WebSocket |

**Cost to reach ₹1–1.50/min:** Already achieved at ₹1.21/min. The floor is Vobiz SIP ₹1.00 + LiveKit ₹0.17 = ₹1.17/min fixed. Gemini 3.1 preview is free tier so Gemini cost ≈ ₹0/min in practice.

---

## 8. Agent Tools (9 total)

All tools are methods on `AppointmentTools(llm.ToolContext)` in `tools.py`.  
Toggle on/off per-deployment via `ENABLED_TOOLS` JSON setting in Supabase.

| Tool | When agent calls it |
|---|---|
| `check_availability(date, time)` | Before confirming any slot |
| `book_appointment(name, phone, date, time, service)` | After verbal confirmation |
| `end_call(outcome, reason)` | Always at call end — logs outcome to Supabase |
| `transfer_to_human(reason)` | Lead asks for human / angry / complex objection |
| `send_sms_confirmation(phone, message)` | After successful booking (if Twilio configured) |
| `lookup_contact(phone)` | At call start — retrieves memories + call history + appointments |
| `remember_details(insight)` | Mid-call — stores key insight about the lead |
| `book_calcom(name, email, date, start_time)` | After `book_appointment` — syncs to Cal.com |
| `cancel_calcom(booking_uid)` | When appointment is cancelled |

**Contact memory flow:**
1. Agent calls `remember_details("Prefers morning calls, has 2 kids")` during conversation
2. Stored in `contact_memory` table per phone number
3. After 5+ entries, Gemini 2.0 Flash auto-compresses them into a concise profile
4. `lookup_contact` shows memories first, then call history, then appointments

**Tool filtering:**
```python
# In agent.py
enabled_tools = await get_enabled_tools()   # [] = all enabled
active_tools = tool_ctx.build_tool_list(enabled_tools)
```

---

## 9. Campaign Scheduler

Mass calling with APScheduler in `server.py`:

```python
# Create campaign
POST /api/campaigns  {name, contacts:[{phone,lead_name,business_name,service_type},...],
                      schedule_type:"daily", schedule_time:"09:00", call_delay_seconds:3}

# Run now (ignores schedule)
POST /api/campaigns/{id}/run

# Pause / resume scheduled campaign
PATCH /api/campaigns/{id}/status  {status: "paused" | "active"}
```

Schedule types:
- `once` → dispatches immediately when created
- `daily` → fires every day at `schedule_time` (APScheduler CronTrigger)
- `weekdays` → fires Mon–Fri at `schedule_time`

Campaign runner dispatches calls sequentially with `call_delay_seconds` between each, updating `total_dispatched` / `total_failed` on completion.

---

## 10. Cal.com Integration

```python
# book_calcom tool — uses Cal.com REST API v1
POST https://api.cal.com/v1/bookings
Headers: Authorization: Bearer {CALCOM_API_KEY}
Body: {eventTypeId, start (ISO), timeZone, responses:{name, email, notes}, metadata}

# cancel_calcom tool
DELETE https://api.cal.com/v1/bookings/{uid}
```

Required settings: `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID`, `CALCOM_TIMEZONE`.  
Event Type ID is the number in your Cal.com event URL.

---

## 11. CRM & Contact Memory

Dashboard tab "👥 CRM":
- Aggregates `call_logs` by phone number → shows total calls, booking count, last outcome
- Drill-down per contact → full call history with editable notes
- Recording playback links (if S3/Supabase Storage configured)

Memory compression (background task in `tools.py`):
```python
async def _compress_memories(self):
    memories = await get_contact_memory(self.phone_number)
    if len(memories) < 5: return
    model = genai.GenerativeModel("gemini-2.0-flash")
    compressed = model.generate_content(f"Compress these notes...\n{bullet_list}").text
    await compress_contact_memory(self.phone_number, compressed)
```

---

## 12. Recording (LiveKit Egress)

Fires automatically if S3 credentials are present. Non-fatal (skipped without error if not configured):

```python
if _aws_key and _aws_secret and _aws_bucket:
    egress = await ctx.api.egress.start_room_composite_egress(
        api.RoomCompositeEgressRequest(
            room_name=ctx.room.name, audio_only=True,
            file_outputs=[api.EncodedFileOutput(
                file_type=api.EncodedFileType.OGG,
                filepath=f"recordings/{ctx.room.name}.ogg",
                s3=api.S3Upload(access_key=..., secret=..., bucket=..., region=..., endpoint=...),
            )],
        )
    )
    tool_ctx.recording_url = f"{s3_ep}/{bucket}/{path}"
```

---

## 13. SIP Trunk Setup (One-time)

```
Settings tab → Group 3 (Vobiz) → fill in SIP Domain, Username, Password, Outbound Number
→ Click "⚡ Create SIP Trunk in LiveKit" → saves OUTBOUND_TRUNK_ID to Supabase
```

Trunk creation via LiveKit API:
```python
trunk = await lk.sip.create_sip_outbound_trunk(
    lk_api.CreateSIPOutboundTrunkRequest(
        trunk=lk_api.SIPOutboundTrunkInfo(
            name="Vobiz Outbound Trunk",
            address=sip_domain,
            auth_username=username, auth_password=password, numbers=[phone],
        )
    )
)
```

---

## 14. Production Startup

```bash
# start.sh — IMPORTANT: hardcode port 8000. LiveKit agent uses 8081 internally.
# Never use $PORT from hosting env for uvicorn.
uvicorn server:app --host 0.0.0.0 --port 8000 &
python agent.py start
```

Worker options:
```python
agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="outbound-caller")
```

Agent name **must match** the `agent_name` in `create_dispatch()` calls from the server.

---

## 15. Known Gotchas

| Symptom | Root Cause | Fix |
|---|---|---|
| Agent goes silent 30s–2 min into call | Silence configs broken — `EndSensitivity.LOW` is wrong enum | Use `EndSensitivity.END_SENSITIVITY_LOW` (full string form required) |
| All silence-prevention configs silently skipped | Exception in try/except hides the enum error | Check for "Could not build silence-prevention config" in logs |
| `generate_reply` ignored, no initial greeting | Using gemini-3.1-* model — plugin explicitly blocks it | 3.1 speaks autonomously from system prompt; no workaround needed |
| `session.say()` + Deepgram TTS produces no audio | TTS audio doesn't route through SIP leg properly | Remove Deepgram TTS workaround — model speaks without it |
| `gemini-2.0-flash-live-001` → 1008 policy violation | Model inaccessible on standard API keys (v1alpha + v1beta both fail) | Use `gemini-3.1-flash-live-preview` instead |
| `AgentSession isn't running` | Session started before SIP call answered | Dial-first pattern (Section 4) |
| `DefaultCredentialsError` on TTS | Used `google.TTS` which needs ADC, not Gemini API key | Don't attach any extra TTS for realtime models |
| `duplicate function name` on tools | Passed tools to both `super().__init__()` and `AgentSession` | Pass `tools=[]` to `super().__init__()`, pass to `AgentSession` only |
| Port 8081 already in use on restart | Previous worker not fully killed | `pkill -9 -f "agent.py start"` then wait 2s before restart |
| Worker uses old model after DB change | `load_db_settings_to_env()` only runs at startup | Must restart agent worker after changing model in Settings |
| Lite model not working for live audio | e.g. gemini-3.1-flash-lite-preview lacks `bidiGenerateContent` | Use `gemini-3.1-flash-live-preview` |

---

## 16. Dashboard Tabs

| Tab | What it does |
|---|---|
| 📊 Stats | Live KPIs + **Live Config card** (current model, forwarding #, Cal.com status, prompt) |
| 📞 Single Call | Dispatch one call with optional per-call prompt override |
| 📋 Batch Call | CSV upload → sequential dispatch with progress bar |
| 🚀 Campaigns | Named campaigns with once/daily/weekdays scheduler |
| ✏️ AI Prompt | Global system prompt editor; supports `{lead_name}`, `{business_name}`, `{service_type}` |
| 📅 Appointments | Booked appointments with date filter + cancel |
| 📝 Call Logs | Paginated call history |
| 👥 CRM | Contact aggregation + per-contact drill-down + notes + recording links |
| ⚙️ Settings | BYOK: LiveKit, Gemini (model+voice), Vobiz, Twilio, S3, Cal.com, Tool Toggles |
| 📋 Logs | Live log viewer with level/source filters + auto-refresh |
| 🔧 Setup | Quickstart guide + cost breakdown + troubleshooting |
