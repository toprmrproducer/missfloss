# ⚡ Quick Start — OutboundAI

> Get from zero to making AI voice calls in under 30 minutes.

---

## What you need before starting

| Thing | Where to get it | Free? |
|---|---|---|
| LiveKit account | [cloud.livekit.io](https://cloud.livekit.io) | ✅ Free tier |
| Google Gemini API key | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) | ✅ Free |
| Supabase account | [supabase.com](https://supabase.com) | ✅ Free tier |
| Vobiz SIP account | [vobiz.ai](https://vobiz.ai) | 💰 Paid (₹/min) |
| Coolify server (VPS) | Any VPS with Docker — [Hetzner](https://hetzner.com), [DigitalOcean](https://digitalocean.com) | 💰 ~$5–10/mo |

---

## 5-step setup

### Step 1 — Create Supabase tables
1. Go to [supabase.com](https://supabase.com) → your project → **SQL Editor**
2. Paste the entire contents of `supabase_schema.sql` (in the repo root)
3. Click **Run** — you should see "Success. No rows returned"

### Step 2 — Deploy on Coolify
See `docs/01-DEPLOY-COOLIFY.md` for the full walkthrough.

Short version:
1. Create a new Resource → GitHub repo → Dockerfile
2. Add all environment variables from `docs/02-ENV-VARIABLES.md`
3. Deploy

### Step 3 — Get your API keys
Follow `docs/03-API-KEYS.md` — each key takes 2–5 minutes to get.

### Step 4 — Configure via the Dashboard
Once deployed, open your app URL:
1. Go to **⚙️ Settings** → fill in LiveKit, Gemini, Vobiz keys
2. Under **Vobiz**, click **⚡ Create SIP Trunk in LiveKit**
3. Go to **✏️ AI Prompt** → tweak the default prompt for your business

### Step 5 — Make your first call
1. Go to **📞 Single Call**
2. Enter a phone number (E.164 format: `+919876543210`)
3. Enter lead name, business name, service type
4. Click **▶ Start Call**
5. Your phone will ring in ~5 seconds

---

## Checklist before going live

- [ ] Supabase schema SQL ran without errors
- [ ] LiveKit URL, API Key, API Secret saved in Settings
- [ ] Google Gemini API key saved in Settings
- [ ] Vobiz SIP domain, username, password, outbound number saved
- [ ] SIP Trunk created (green ✓ in Settings → Vobiz)
- [ ] AI Prompt customised for your business
- [ ] Test call to yourself succeeded
- [ ] Agent spoke and you could hear it clearly

---

## File map

```
agent.py          ← AI voice agent (LiveKit worker)
server.py         ← REST API + Campaign scheduler (FastAPI)
db.py             ← All database operations (Supabase)
tools.py          ← AI tools (book_appointment, end_call, etc.)
prompts.py        ← Default system prompt template
start.sh          ← Production startup script
Dockerfile        ← Docker container definition
supabase_schema.sql  ← Run once to create all tables
ui/index.html     ← Dashboard (single HTML file, no build step)
docs/             ← You are here
```
