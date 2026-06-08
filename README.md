# Outbound AI Appointment Booking Agent

Ultra-cheap, production-ready AI outbound calling system built on LiveKit + Gemini Live + Vobiz SIP.

**Target cost: ≤ ₹1.50 per minute, all-in.**

---

## Architecture

```
Phone caller
    │
    │  PSTN
    ▼
Vobiz SIP Trunk
    │
    │  SIP/RTP
    ▼
LiveKit Room ◄──► Agent Worker (agent.py)
                       │
                       │  WebSocket (single connection)
                       ▼
               Gemini Live API
           (STT + LLM + TTS in one)
                       │
                       │  Tools (SQLite)
                       ▼
               AppointmentTools
      check_availability / book_appointment
      end_call / transfer_to_human / send_sms
```

---

## Cost Breakdown (per 1-minute call)

| Service | Cost | Notes |
|---|---|---|
| Vobiz SIP | ≈ ₹1.00/min | Fixed telephony cost |
| Gemini 2.0 Flash Live | ≈ ₹0.03/min | Free tier up to quota |
| LiveKit Cloud | ≈ ₹0.17/min | Free tier available |
| **Total** | **≈ ₹1.20/min** | ✅ Under ₹1.50 target |

---

## Prerequisites

- Python 3.11+
- A [LiveKit Cloud](https://cloud.livekit.io/) account (free tier works)
- A [Vobiz](https://console.vobiz.ai/) account with an outbound SIP trunk configured
- A [Google AI Studio](https://aistudio.google.com/) account for a free Gemini API key

---

## 1. Installation

```bash
# Clone / navigate to the project directory
cd "Outbound Mass Caller"

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Configuration

```bash
cp .env.example .env
```

Open `.env` and fill in **at minimum**:

```env
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
GOOGLE_API_KEY=AIza...
OUTBOUND_TRUNK_ID=ST_...
VOBIZ_SIP_DOMAIN=...
VOBIZ_USERNAME=...
VOBIZ_PASSWORD=...
DEFAULT_TRANSFER_NUMBER=+91...
```

---

## 3. Database Setup

Run once to create the SQLite tables:

```bash
python -c "from db import init_db; init_db(); print('DB ready.')"
```

---

## 4. SIP Trunk Setup

Sync your Vobiz credentials to the LiveKit SIP trunk:

```bash
python setup_trunk.py
```

You only need to run this once (or after changing Vobiz credentials).

---

## 5. Running the Agent

```bash
python agent.py start
```

The agent registers as `outbound-caller` and waits for dispatched jobs. Keep this terminal open.

For development with hot reload:

```bash
python agent.py dev
```

---

## 6. Running the API Server

In a separate terminal:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

---

## 7. Making Your First Call

**Single call:**

```bash
python make_call.py \
  --phone +919876543210 \
  --lead "Rahul Sharma" \
  --business "HealthFirst Clinic" \
  --service "Dental Checkup"
```

**Batch from CSV:**

```bash
python make_call.py --batch leads.csv --delay 3
```

CSV format (`leads.csv`):
```csv
phone,lead_name,business_name,service_type
+919876543210,Rahul Sharma,HealthFirst Clinic,Dental Checkup
+919123456789,Priya Mehta,HealthFirst Clinic,Eye Test
```

**Custom script per campaign:**

```bash
python make_call.py --phone +91... --system_prompt_file my_script.txt
```

---

## 8. Opening the Dashboard

```
http://localhost:8000
```

The dashboard shows live stats, call logs, appointments, and lets you trigger calls from the browser.

---

## 9. File Structure

```
.
├── agent.py          # Main LiveKit agent (Gemini Live AI brain)
├── make_call.py      # CLI dispatcher — single or batch
├── db.py             # SQLite helpers (appointments + call logs)
├── tools.py          # AppointmentTools — all 5 function tools
├── prompts.py        # System prompt template + interpolation
├── server.py         # FastAPI backend — 5 API endpoints + UI
├── setup_trunk.py    # One-time SIP trunk configuration
├── ui/
│   └── index.html    # Dashboard (single-file, no framework)
├── requirements.txt
├── .env.example
└── appointments.db   # Created automatically on first run
```

---

## 10. Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Status 500 (Max Auth Retry)` | Wrong Vobiz credentials on trunk | Run `python setup_trunk.py` to resync |
| `OUTBOUND_TRUNK_ID not set` | Missing env var | Set `OUTBOUND_TRUNK_ID=ST_...` in `.env` |
| `No module named 'livekit.plugins.google'` | Plugin not installed | `pip install livekit-plugins-google>=1.0.0` |
| `GOOGLE_API_KEY` not found | Missing API key | Add `GOOGLE_API_KEY=AIza...` to `.env` |
| `Status 408 (Timeout)` on transfer | SIP REFER not enabled | Enable "Call Transfer" in Vobiz console settings |
| Dashboard shows no data | Server not running or DB empty | Start `uvicorn server:app ...` and make a test call |

---

## Switching to Pipeline Mode

If Gemini Live is unreliable in your region, add to `.env`:

```env
USE_GEMINI_REALTIME=false
DEEPGRAM_API_KEY=your_deepgram_key
```

This activates the Deepgram STT → Gemini LLM → Google TTS pipeline. Cost rises to ≈ ₹1.78/min.
