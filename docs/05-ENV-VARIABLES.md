# 🔧 Environment Variables — Complete Reference

Add all of these in Coolify → your service → **Environment Variables**.

---

## Required (app won't start without these)

```env
# ── Supabase ──────────────────────────────────────────
SUPABASE_URL=https://xxxxxxxxxxxxxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# ── LiveKit ───────────────────────────────────────────
LIVEKIT_URL=wss://your-project-abc123.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Google Gemini ─────────────────────────────────────
GOOGLE_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_TTS_VOICE=Aoede
USE_GEMINI_REALTIME=true

# ── Vobiz SIP Telephony ───────────────────────────────
VOBIZ_SIP_DOMAIN=xxxxxxxx.sip.vobiz.ai
VOBIZ_USERNAME=your_username
VOBIZ_PASSWORD=your_password
VOBIZ_OUTBOUND_NUMBER=+919876543210
OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxxxxxx
DEFAULT_TRANSFER_NUMBER=+919876543210
```

---

## Optional — Call Recordings (Supabase Storage)

```env
S3_ACCESS_KEY_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
S3_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
S3_ENDPOINT_URL=https://xxxxxxxxxxxxxxxx.supabase.co/storage/v1/s3
S3_REGION=ap-northeast-1
S3_BUCKET=call-recordings
```

---

## Optional — Calendar Sync (Cal.com)

```env
CALCOM_API_KEY=cal_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CALCOM_EVENT_TYPE_ID=123456
CALCOM_TIMEZONE=Asia/Kolkata
```

---

## Optional — SMS Confirmations (Twilio)

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+1234567890
```

---

## Optional — Pipeline Mode (Deepgram STT)

Only needed if you set `USE_GEMINI_REALTIME=false`. Not required for the default Gemini Live setup.

```env
DEEPGRAM_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
USE_GEMINI_REALTIME=false   # only if switching to pipeline mode
```

---

## Notes

| Variable | Notes |
|---|---|
| `GEMINI_MODEL` | Must be a Live-capable model. Only `gemini-3.1-flash-live-preview` works reliably on standard API keys. Do not use `gemini-2.0-flash-live-001` — it returns a 1008 policy error. |
| `GEMINI_TTS_VOICE` | The global default voice. Can be overridden per agent profile. See `docs/06-VOICES.md` for full list. |
| `OUTBOUND_TRUNK_ID` | Leave blank initially. After saving Vobiz keys in the Settings tab, click "⚡ Create SIP Trunk in LiveKit" — this auto-fills the trunk ID. |
| `DEFAULT_TRANSFER_NUMBER` | The number the AI calls when a lead requests a human agent. Usually your own mobile number. |
| `USE_GEMINI_REALTIME` | Keep `true`. Set to `false` only if Gemini Live is unavailable in your region. |
| All S3 variables | All optional. If absent, recordings are skipped silently. |
| All Cal.com variables | Optional. If absent, `book_calcom` tool is skipped. |
| All Twilio variables | Optional. If absent, `send_sms_confirmation` tool is skipped. |

---

## How settings priority works

Settings are loaded in this order (later wins):

1. **Hardcoded fallback** — empty strings (no defaults in code)
2. **Coolify env vars** — what you set in the deployment panel
3. **Supabase Settings tab** — keys saved via the dashboard UI at runtime

So: anything you save in the dashboard **Settings tab** overrides Coolify env vars, which override the code defaults. This means you can update API keys without redeploying — just save them in the Settings tab.

> Exception: `GEMINI_MODEL` changes in the Settings tab require an agent worker restart (redeploy) to take effect, because the model is loaded once at startup.
