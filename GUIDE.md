# OutboundAI — Complete No-Code User Guide

> You don't need to understand any of the code to use this system.  
> This guide explains everything in plain English — what it does, how to set it up, and how to use every feature.

---

## Table of Contents

1. [What Is This System?](#1-what-is-this-system)
2. [How It Works (Plain English)](#2-how-it-works-plain-english)
3. [What You Need Before You Start](#3-what-you-need-before-you-start)
4. [Getting Your API Keys](#4-getting-your-api-keys)
5. [Setting Up Your .env File](#5-setting-up-your-env-file)
6. [Starting the System](#6-starting-the-system)
7. [Using the Dashboard — Tab by Tab](#7-using-the-dashboard--tab-by-tab)
8. [Customising Your AI Agent's Personality](#8-customising-your-ai-agents-personality)
9. [Making Your First Call](#9-making-your-first-call)
10. [Running a Batch Campaign](#10-running-a-batch-campaign)
11. [Reading Your Results](#11-reading-your-results)
12. [Frequently Asked Questions](#12-frequently-asked-questions)
13. [What To Do When Something Goes Wrong](#13-what-to-do-when-something-goes-wrong)

---

## 1. What Is This System?

This is an **AI-powered outbound phone calling agent**. You give it a list of phone numbers (or just one number), and it automatically calls each person, has a real conversation with them in a human-like voice, and tries to book them an appointment.

**Think of it like hiring a virtual receptionist** that:
- Calls people on your behalf
- Introduces itself as "Priya from [your business]" (fully customisable)
- Asks about their availability
- Checks your calendar for open slots
- Books the appointment if they agree
- Sends them an SMS confirmation (optional)
- Logs every call outcome so you can see your results

You control everything through a web dashboard that looks like this:

```
┌──────────────────────────────────────────────────────┐
│ ⬡ OutboundAI   [Dashboard]                  17:42:31 │
├──────────────────────────────────────────────────────┤
│ 📊 Stats │ 📞 Single │ 📋 Batch │ ✏️ Prompt │ 📅 Appts │
└──────────────────────────────────────────────────────┘
```

---

## 2. How It Works (Plain English)

Here is what happens from the moment you click "Start Call" to the moment the phone call ends:

```
You click "Start Call" in the dashboard
        │
        ▼
The server creates a virtual room (LiveKit)
        │
        ▼
An AI worker joins the room and dials the phone number (via Vobiz)
        │
        ▼
The person picks up. The AI says: "Hi, am I speaking with Rahul?"
        │
        ├── Person says YES → AI proceeds with appointment pitch
        │
        ├── Wrong person → AI apologises and hangs up
        │
        └── Voicemail → AI leaves a message and hangs up
                │
                ▼
        Person agrees to a time → AI checks calendar → Books it → Confirms
                │
                ▼
        Outcome saved to database → You see it in Call Logs
```

**The AI brain is Google Gemini Live.** This is a single API that handles:
- Listening to the person talking (Speech-to-Text)
- Understanding what they said and deciding what to say next (LLM)
- Speaking the response in a natural voice (Text-to-Speech)

All three happen in one real-time connection — which is why it sounds natural and responds fast.

---

## 3. What You Need Before You Start

### Computer / Server
- A computer running **macOS, Linux, or Windows with WSL**
- At least 1 GB of free RAM
- Python 3.11 or newer installed
  - Check: open Terminal, type `python --version` or `python3 --version`
  - If you don't have it: download from [python.org](https://www.python.org/downloads/)

### Accounts to Create (all free to start)

| Account | Time to Create | Cost |
|---|---|---|
| [LiveKit Cloud](https://cloud.livekit.io) | ~2 minutes | Free tier |
| [Google AI Studio](https://aistudio.google.com) | ~1 minute | Free tier |
| [Vobiz](https://console.vobiz.ai) | Already have | ~₹1/min |

---

## 4. Getting Your API Keys

### API Key 1 — LiveKit (free)

LiveKit is the "phone switchboard" — it connects the AI to your Vobiz phone line.

1. Go to [cloud.livekit.io](https://cloud.livekit.io)
2. Click **Sign Up** → create an account with your email
3. After logging in, click **New Project** → give it any name (e.g. "My Caller")
4. Go to **Settings** → **Keys** in the left sidebar
5. You'll see three values — copy all three:

```
LIVEKIT_URL      = wss://your-project-name.livekit.cloud
LIVEKIT_API_KEY  = APIxxxxxxxxxxxxxxxx
LIVEKIT_API_SECRET = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> 💡 The URL starts with `wss://` (WebSocket Secure). This is normal — it's not a website URL.

---

### API Key 2 — Google Gemini (free)

Gemini is the AI brain — it listens, thinks, and speaks.

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Click **Create API Key**
4. Select **Create API key in new project** (or use existing)
5. Copy the key that appears (starts with `AIza...`)

```
GOOGLE_API_KEY = AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> 💡 This key gives access to Gemini's free tier — you get millions of tokens per day for free. You'll almost certainly never hit the limit for outbound calling.

---

### API Key 3 — Vobiz (you already have this)

You already have a Vobiz account. You need four pieces of information from your Vobiz console:

1. Log in at [console.vobiz.ai](https://console.vobiz.ai)
2. Find your **SIP Domain** — looks like `youraccount.sip.vobiz.ai`
3. Find your **SIP Username** (usually your account username)
4. Find your **SIP Password**
5. Find your **DID number** (the phone number Vobiz assigned you, e.g. `+917012345678`)

```
VOBIZ_SIP_DOMAIN       = youraccount.sip.vobiz.ai
VOBIZ_USERNAME         = your_username
VOBIZ_PASSWORD         = your_password
VOBIZ_OUTBOUND_NUMBER  = +917012345678
```

**You also need the Trunk ID from LiveKit.** This links LiveKit to Vobiz:
- After setting up your LiveKit project (above), go to the **SIP** section in the left sidebar
- You should see a trunk that was created — its ID starts with `ST_`
- If you don't see one, run the setup script (covered in Step 6)

---

### Optional — Twilio SMS (skip if you don't need texts)

If you want the AI to send an SMS confirmation after booking:

1. Go to [console.twilio.com](https://console.twilio.com)
2. Create an account (free trial gives you a phone number and some credit)
3. Copy your Account SID and Auth Token from the dashboard
4. Get a Twilio phone number (the "From" number)

```
TWILIO_ACCOUNT_SID  = ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN   = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER  = +12015551234
```

> Leave these blank in .env if you don't want SMS — the system will skip it silently.

---

## 5. Setting Up Your .env File

The `.env` file is where you store all your API keys. It's like a settings file that the system reads when it starts.

### Step 1 — Create the file

Open your terminal in the project folder and run:

```bash
cp .env.example .env
```

This copies the example file so you have a template to fill in.

### Step 2 — Open the file

You can open `.env` in any text editor:
- **Mac**: TextEdit, VS Code, Sublime Text
- **Windows**: Notepad, Notepad++
- **Any OS**: VS Code (`code .env`)

### Step 3 — Fill in your values

Replace the placeholder values with your real keys. Here's an example of a filled-in `.env`:

```env
# LiveKit
LIVEKIT_URL=wss://my-clinic.livekit.cloud
LIVEKIT_API_KEY=APIabc123def456
LIVEKIT_API_SECRET=supersecretvalue123456789

# Google Gemini
GOOGLE_API_KEY=AIzaSyABCDEF1234567890
GEMINI_MODEL=gemini-2.0-flash-live-001
GEMINI_TTS_VOICE=Aoede

# Vobiz
VOBIZ_SIP_DOMAIN=myclinic.sip.vobiz.ai
VOBIZ_USERNAME=myclinic_user
VOBIZ_PASSWORD=mypassword123
VOBIZ_OUTBOUND_NUMBER=+917012345678
OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxxxxxxxx
DEFAULT_TRANSFER_NUMBER=+919999999999

# Leave these blank if you don't want SMS
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
```

> ⚠️ **Important:** Never share your `.env` file with anyone. It contains your private API keys.

### Choosing a Voice

The AI can speak in different voices. Set `GEMINI_TTS_VOICE` to one of:

| Voice Name | Character |
|---|---|
| `Aoede` | Warm, female (default — works great for "Priya") |
| `Puck` | Bright, energetic |
| `Charon` | Deep, calm |
| `Kore` | Soft, natural female |
| `Fenrir` | Confident male |
| `Orbit` | Clear, professional |

---

## 6. Starting the System

Every time you want to use the system, you need to run **two commands** in two separate terminal windows.

### First time only — Install & Setup

```bash
# Install all dependencies (run once)
pip install -r requirements.txt

# Set up your database (run once)
python -c "from db import init_db; init_db()"

# Sync your Vobiz credentials to LiveKit (run once, or after changing Vobiz password)
python setup_trunk.py
```

If `setup_trunk.py` prints `✅ SIP Trunk updated successfully!` — you're good to go.

---

### Every time — Start the system

**Terminal Window 1** — The AI Worker (keep this running):
```bash
python agent.py start
```

You'll see something like:
```
INFO:livekit.agents:starting worker...
INFO:outbound-agent:worker registered as 'outbound-caller'
```
This means the AI is waiting for calls to be dispatched.

**Terminal Window 2** — The Dashboard:
```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

You'll see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

Now open your browser and go to: **http://localhost:8000**

---

## 7. Using the Dashboard — Tab by Tab

### 📊 Stats Tab (Home)

This is the first thing you see. It shows live numbers that update every 10 seconds:

| Card | What it means |
|---|---|
| **Total Calls** | How many calls have been dispatched in total |
| **Booked** | How many resulted in a confirmed appointment |
| **Not Interested** | How many leads declined |
| **Booking Rate %** | Percentage of calls that became bookings |
| **Avg Duration (s)** | Average call length in seconds |

---

### 📞 Single Call Tab

Use this to call **one person right now**.

**Fields to fill in:**
- **Phone Number** — Must include country code. Example: `+919876543210`
- **Lead Name** — The person's name. The AI uses this to greet them: *"Hi, am I speaking with Rahul?"*
- **Business Name** — Your clinic/business name. Example: `HealthFirst Clinic`
- **Service Type** — What you're calling about. Example: `Dental Checkup`

**System Prompt Override:**
- Normally the AI uses whatever prompt you've saved in the ✏️ AI Prompt tab
- Tick the checkbox **"Override system prompt for this call only"** if you want to use a completely different script just for this one call
- A text area will appear where you can paste your custom script

Click **▶ Start Call** — you'll see a confirmation toast at the bottom right.

---

### 📋 Batch Call Tab

Use this to call **many people at once** from a spreadsheet.

**Step 1 — Prepare your CSV file**

Open Excel or Google Sheets and create a table like this:

| phone | lead_name | business_name | service_type |
|---|---|---|---|
| +919876543210 | Rahul Sharma | HealthFirst Clinic | Dental Checkup |
| +919123456789 | Priya Mehta | HealthFirst Clinic | Eye Test |
| +918765432100 | Amit Patel | HealthFirst Clinic | Blood Test |

Save it as a `.csv` file (in Excel: File → Save As → CSV).

> **Rules:**
> - Phone numbers must start with `+` and include country code
> - The header row is required
> - Column names must be exactly as shown above (lowercase)

**Step 2 — Upload and start**

1. Optionally tick **"Use a custom system prompt for the entire batch"** if this campaign has a different script
2. Click **📂 Parse CSV** — you'll see a preview of the first 10 rows
3. Set the **delay between calls** (default: 3 seconds — don't set lower than 2 to avoid spam flags)
4. Click **▶ Start Batch** — a progress bar shows each call being dispatched

---

### ✏️ AI Prompt Tab

This is where you control **what your AI agent says and how it behaves**.

This is the most powerful tab. Everything about the AI's personality, script, and behaviour lives here.

**The Variables** — use these in your prompt and they get filled in automatically per call:

| Variable | Gets replaced with |
|---|---|
| `{lead_name}` | The lead's name (e.g. "Rahul") |
| `{business_name}` | Your business name (e.g. "HealthFirst Clinic") |
| `{service_type}` | The service type (e.g. "Dental Checkup") |

**How to use this tab:**

1. You'll see the current prompt loaded in the big text editor
2. Make any changes you want (see next section for examples)
3. Click **💾 Save Prompt** — all future calls will immediately use this prompt
4. Click **↩ Reset to Default** to go back to the original Priya script

> 💡 Changes take effect on the **next** call dispatched. Any call already in progress uses the old prompt.

---

### 📅 Appointments Tab

Shows all booked appointments. You can:
- **Filter by date** — use the date picker to see appointments on a specific day
- **Cancel** — click the red Cancel button next to any booking

---

### 📝 Call Logs Tab

Shows every call that was made. Columns:

| Column | What it means |
|---|---|
| Phone | Number that was called |
| Lead | Lead's name |
| Outcome | What happened (see below) |
| Reason | Why it ended that way |
| Duration | How long the call lasted |
| Timestamp | When it was made |

**Outcome types:**

| Outcome | Meaning |
|---|---|
| 🟢 booked | Appointment successfully booked |
| 🔴 not_interested | Lead declined |
| 🟡 voicemail | AI left a voicemail |
| ⚪ wrong_number | Wrong person answered |
| 🔵 callback_requested | Lead asked to be called back later |

---

### 🔧 Setup Guide Tab

Built-in reference with API key links, cost breakdown, and troubleshooting. Always available in the dashboard.

---

## 8. Customising Your AI Agent's Personality

Go to the **✏️ AI Prompt** tab. Here's how to customise for common scenarios:

### Change the agent's name

Find this line in the prompt:
```
You are Priya, a friendly and professional appointment booking assistant...
```
Change `Priya` to whatever name you want:
```
You are Aryan, a friendly sales executive calling on behalf of {business_name}.
```

### Change the language / tone

Add to the STYLE RULES section:
```
- Always speak in Hinglish (mix of Hindi and English) naturally.
- Use "ji" as a respectful suffix occasionally.
- Address the lead as "aap" not "tum".
```

### Change the goal (not appointment booking)

Replace the CALL FLOW section entirely. Example for a follow-up survey:
```
YOUR GOAL: Collect feedback from {lead_name} about their recent visit to {business_name}.

CALL FLOW:
1. OPEN: "Hi, am I speaking with {lead_name}? I'm calling from {business_name} to collect feedback about your recent visit."
2. SURVEY: Ask 3 short questions about their experience (1-5 scale).
3. CLOSE: Thank them and end the call.
```

### Make it more aggressive / persistent

Change the QUALIFY section:
```
3. QUALIFY
   After first refusal — offer a strong incentive: "We're running a 50% off promotion this week only."
   After second refusal — ask for a specific future date.
   After third refusal → end_call(outcome='not_interested').
```

### Add Hindi/regional language greeting

Modify the OPEN step:
```
1. OPEN
   Say: "Namaste! Kya main {lead_name} ji se baat kar sakta/sakti hoon?"
   If they respond in English, switch to English automatically.
   If they respond in Hindi, stay in Hindi.
```

---

## 9. Making Your First Call

**Recommended test sequence:**

1. Call your **own mobile number** first
2. Use `+91XXXXXXXXXX` (your number with country code)
3. Set Lead Name to your own name, Business to a test name
4. Answer the call and have a conversation with the AI
5. Try saying "Transfer me to a human" — it should transfer to your `DEFAULT_TRANSFER_NUMBER`
6. Try saying "Book me for tomorrow at 10 AM" — it should book in the database
7. Check the 📅 Appointments tab — you should see your booking
8. Check the 📝 Call Logs tab — you should see the call logged

If all of that works, you're ready to call real leads.

---

## 10. Running a Batch Campaign

### Preparing your CSV

Best practice for the CSV file:
- Clean the phone numbers first (remove spaces, dashes, brackets)
- Make sure every number has the country code (`+91` for India)
- One row per person — no duplicates
- Save as CSV (UTF-8 encoding if your names have regional characters)

### Recommended delay settings

| Use case | Delay setting |
|---|---|
| Testing (small batch) | 5 seconds |
| Normal campaign | 3 seconds |
| High-volume (careful with Vobiz limits) | 2 seconds |

### During the batch

- **Don't close the browser tab** — the batch runs in the browser
- Watch the progress bar
- If a call fails, it's logged with "fail" in the status — other calls continue
- Check Call Logs after the batch finishes

### After the batch

- Go to 📊 Stats to see your booking rate
- Go to 📅 Appointments to see who got booked
- Export your results by checking Call Logs

---

## 11. Reading Your Results

### Good benchmark numbers for outbound calling:
- **Booking rate of 5–15%** is normal for cold outbound
- **Average call duration of 45–120 seconds** — longer = better engagement
- **Voicemail rate of 30–50%** is normal depending on time of day

### Best times to call (India):
- **10 AM – 12 PM** — people are awake and not yet busy
- **5 PM – 7 PM** — end of workday, receptive
- **Avoid:** Early morning before 9 AM, lunch 1–2 PM, after 8 PM

---

## 12. Frequently Asked Questions

**Q: Can the AI actually understand Hindi?**  
A: Yes. Gemini Live supports multilingual real-time audio including Hindi, Hinglish, Tamil, and other Indian languages. The AI will follow the lead's language if you include "Match the language the lead uses" in your prompt (it's there by default).

**Q: What happens if no one picks up?**  
A: If the call rings for 8+ seconds with no answer, it will be logged as `voicemail` or the call will fail to connect. No voicemail is left unless a human-sounding automated greeting is detected.

**Q: What if someone says "stop calling me"?**  
A: The AI is prompted to apologise sincerely and end the call with outcome `not_interested`. It will not call them again (though you need to manually remove them from future CSV batches).

**Q: Can I run multiple calls at the same time?**  
A: Yes. LiveKit supports multiple concurrent rooms. The agent worker can handle multiple calls simultaneously. For large volumes, you may need to scale the worker (the Docker guide covers this).

**Q: How do I change the agent's name from "Priya"?**  
A: Go to ✏️ AI Prompt tab and edit the first line of the prompt. Change `Priya` to any name.

**Q: The AI booked a wrong time — how do I cancel?**  
A: Go to 📅 Appointments tab → click Cancel next to the appointment.

**Q: How much does it cost per call?**  
A: Approximately ₹1.20 per minute all-in. A typical call is 1–2 minutes, so ₹1.20–₹2.40 per call.

**Q: What is the `DEFAULT_TRANSFER_NUMBER` for?**  
A: When a lead says "connect me to a real person", the AI transfers the call to this number. Set it to your actual office/personal number.

**Q: Can I run this without a VPS?**  
A: Yes — you can run it on your laptop. The agent connects to LiveKit Cloud (external server), so calls work as long as your laptop is on and the two terminal windows are running.

---

## 13. What To Do When Something Goes Wrong

### "The call was dispatched but the phone didn't ring"

1. Check Terminal 1 (the agent window) for error messages
2. Common causes:
   - `OUTBOUND_TRUNK_ID` is wrong or missing → run `python setup_trunk.py`
   - `VOBIZ_USERNAME` or `VOBIZ_PASSWORD` is wrong → check Vobiz console
   - Phone number format wrong → must be `+91XXXXXXXXXX` (no spaces)

### "The AI picked up but didn't say anything"

1. The `wait_until_answered=True` flag means the agent waits for the call to connect before speaking
2. If it's silent for more than 5 seconds, check that `GOOGLE_API_KEY` is valid
3. Try opening [aistudio.google.com](https://aistudio.google.com) and sending a test message to verify your key works

### "Dashboard shows an error / won't load"

1. Make sure Terminal 2 (uvicorn) is still running
2. Refresh the page
3. Check that port 8000 isn't used by something else: `lsof -i :8000`

### "500 Max Auth Retry error"

This means Vobiz is rejecting the login. Run:
```bash
python setup_trunk.py
```
Then check your Vobiz credentials in `.env`.

### "Twilio SMS not sending"

1. Check all three Twilio env vars are set correctly
2. Verify the `TWILIO_FROM_NUMBER` is a real Twilio number (not your personal number)
3. Leave all three blank to disable SMS entirely — the booking still works without it

---

*Last updated: April 2026*
