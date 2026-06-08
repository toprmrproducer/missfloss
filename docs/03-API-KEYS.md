# 🔑 API Keys — Where to Get Everything

Every key you need, where to find it, and what to paste where.

---

## 1. LiveKit (Required)

**What it does:** Routes audio between your phone call and the AI agent.

1. Go to [cloud.livekit.io](https://cloud.livekit.io) → Sign up (free)
2. Create a new **Project**
3. Go to **Project Settings** → **Keys**
4. Click **Generate new key pair**

| Variable | What to paste |
|---|---|
| `LIVEKIT_URL` | The WebSocket URL — starts with `wss://` e.g. `wss://myproject-abc123.livekit.cloud` |
| `LIVEKIT_API_KEY` | Starts with `API` e.g. `APIxxxxxxxxxxxxxxxxx` |
| `LIVEKIT_API_SECRET` | Long random string, ~40 characters |

> Free tier includes 100k participant-minutes/month — enough for ~500 calls.

---

## 2. Google Gemini (Required)

**What it does:** Powers the AI voice agent (speech recognition + language model + text-to-speech, all in one).

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API Key**
3. Copy the key (starts with `AIzaSy`)

| Variable | What to paste |
|---|---|
| `GOOGLE_API_KEY` | `AIzaSy...` |
| `GEMINI_MODEL` | `gemini-3.1-flash-live-preview` ← use this exactly |
| `GEMINI_TTS_VOICE` | `Aoede` (default) — see voice list in `docs/06-VOICES.md` |

> The Gemini API has a generous free tier. At preview quality (3.1 model), calls are essentially free until you hit very high volume.

---

## 3. Supabase (Required)

**What it does:** Database for calls, appointments, settings, campaigns, CRM.

1. Go to [supabase.com](https://supabase.com) → Sign up → **New Project**
2. Remember your **database password** — you won't need it but save it
3. Go to **Project Settings** → **API**

| Variable | Where to find it |
|---|---|
| `SUPABASE_URL` | "Project URL" — e.g. `https://abcdefgh.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Under "Project API keys" → **service_role** (NOT anon key) — starts with `eyJ` |

> ⚠️ Use the **service_role** key, NOT the anon key. The anon key has read restrictions that will break the app.

After setting these, run the SQL schema: see `docs/04-SUPABASE-SETUP.md`.

---

## 4. Vobiz SIP (Required for outbound calls)

**What it does:** Telephony — actually dials the phone number.

1. Go to [vobiz.ai](https://vobiz.ai) → Sign up / log in
2. Your credentials are shown in your account dashboard

| Variable | What to paste |
|---|---|
| `VOBIZ_SIP_DOMAIN` | Your SIP domain, e.g. `81b129db.sip.vobiz.ai` |
| `VOBIZ_USERNAME` | Your SIP username |
| `VOBIZ_PASSWORD` | Your SIP password |
| `VOBIZ_OUTBOUND_NUMBER` | The phone number assigned to your account in E.164 format: `+919876543210` |
| `OUTBOUND_TRUNK_ID` | **Leave blank** — auto-filled when you click "⚡ Create SIP Trunk" in the Settings tab |

> After saving Vobiz keys in Settings, click **"⚡ Create SIP Trunk in LiveKit"**. This registers your SIP credentials with LiveKit and saves the trunk ID. Without this step, calls won't connect.

---

## 5. Supabase Storage / S3 for Recordings (Optional)

**What it does:** Saves a recording of every call as an `.ogg` audio file.

### Using Supabase Storage (recommended — you already have Supabase)

1. Go to Supabase → **Storage** → **New Bucket**
2. Name it `call-recordings`, set to **Private**
3. Go to **Project Settings** → **S3 Connection**
4. Enable S3 compatibility and copy the credentials

| Variable | Value |
|---|---|
| `S3_ACCESS_KEY_ID` | From Supabase S3 Connection page |
| `S3_SECRET_ACCESS_KEY` | From Supabase S3 Connection page |
| `S3_ENDPOINT_URL` | `https://<your-ref>.supabase.co/storage/v1/s3` |
| `S3_REGION` | `ap-northeast-1` (always this for Supabase Storage) |
| `S3_BUCKET` | `call-recordings` (whatever you named the bucket) |

### Using AWS S3

| Variable | Value |
|---|---|
| `S3_ACCESS_KEY_ID` | AWS IAM access key ID |
| `S3_SECRET_ACCESS_KEY` | AWS IAM secret access key |
| `S3_REGION` | e.g. `us-east-1` |
| `S3_BUCKET` | Your bucket name |
| `S3_ENDPOINT_URL` | Leave blank for AWS |

---

## 6. Cal.com (Optional — calendar booking sync)

**What it does:** When the AI books an appointment, it also creates a real calendar event in Cal.com.

1. Go to [cal.com](https://cal.com) → Sign up
2. Create an **Event Type** (e.g. "30 min Dental Consultation")
3. Go to **Settings** → **Developer** → **API Keys** → Create key
4. Note the event type ID from the URL: `cal.com/event-types/123456` → ID is `123456`

| Variable | Value |
|---|---|
| `CALCOM_API_KEY` | `cal_live_...` |
| `CALCOM_EVENT_TYPE_ID` | The number from your event URL |
| `CALCOM_TIMEZONE` | e.g. `Asia/Kolkata` |

---

## 7. Deepgram (Optional — only for pipeline mode)

**What it does:** Speech-to-text fallback if you turn off Gemini Live (`USE_GEMINI_REALTIME=false`). Not needed for the default Gemini Live setup.

1. Go to [deepgram.com](https://deepgram.com) → Sign up → **API Keys** → Create
2. Copy the key

| Variable | Value |
|---|---|
| `DEEPGRAM_API_KEY` | Your Deepgram API key |

---

## 8. Twilio SMS (Optional — confirmation texts)

**What it does:** Sends an SMS to the lead after booking an appointment.

1. Go to [twilio.com](https://twilio.com) → Sign up
2. Get a phone number
3. Go to **Console** → copy Account SID and Auth Token

| Variable | Value |
|---|---|
| `TWILIO_ACCOUNT_SID` | `ACxxxxxxxxxxxxxxxx` |
| `TWILIO_AUTH_TOKEN` | Your auth token |
| `TWILIO_FROM_NUMBER` | Your Twilio number in E.164: `+1234567890` |
