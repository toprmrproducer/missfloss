# 💻 Run Locally (Mac & Windows)

---

## Mac

### 1. Install Python 3.11+

Check if you have it:
```bash
python3 --version
```

If not, download from [python.org](https://python.org/downloads) or use Homebrew:
```bash
brew install python@3.11
```

### 2. Clone the repo

```bash
git clone https://github.com/toprmrproducer/outbound.git
cd outbound
```

### 3. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

You'll see `(venv)` in your terminal. **Always activate this before running any command.**

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

This takes 2–3 minutes the first time.

### 5. Create your `.env` file

Copy the example:
```bash
cp .env.example .env   # if exists, otherwise create manually
```

Edit `.env` and fill in your API keys. See `docs/03-API-KEYS.md` for where to get each one.

Minimum required:
```env
SUPABASE_URL=https://xxxxxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxx
GOOGLE_API_KEY=AIzaSy...
VOBIZ_SIP_DOMAIN=xxxxxxxx.sip.vobiz.ai
VOBIZ_USERNAME=your_username
VOBIZ_PASSWORD=your_password
VOBIZ_OUTBOUND_NUMBER=+91XXXXXXXXXX
OUTBOUND_TRUNK_ID=ST_xxxxxxxx
```

### 6. Start the app

```bash
bash start.sh
```

Or start each process separately (two terminal windows):

**Terminal 1 — API server:**
```bash
source venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Agent worker:**
```bash
source venv/bin/activate
python agent.py start
```

### 7. Open the dashboard

Go to [http://localhost:8000](http://localhost:8000)

---

## Windows

### 1. Install Python 3.11+

Download from [python.org/downloads](https://python.org/downloads).

During install: **check "Add Python to PATH"**.

Verify:
```cmd
python --version
```

### 2. Clone the repo

Install Git from [git-scm.com](https://git-scm.com) if needed, then:
```cmd
git clone https://github.com/toprmrproducer/outbound.git
cd outbound
```

### 3. Create a virtual environment

```cmd
python -m venv venv
venv\Scripts\activate
```

### 4. Install dependencies

```cmd
pip install -r requirements.txt
```

### 5. Create `.env`

Create a file called `.env` in the project root (not `.env.txt`) and paste your keys. Use Notepad and make sure "Save as type: All Files".

### 6. Start the app

**Terminal 1:**
```cmd
venv\Scripts\activate
uvicorn server:app --host 0.0.0.0 --port 8000
```

**Terminal 2:**
```cmd
venv\Scripts\activate
python agent.py start
```

### 7. Open the dashboard

Go to [http://localhost:8000](http://localhost:8000)

---

## Common local issues

**`ModuleNotFoundError: No module named 'livekit'`**
→ Your virtual environment isn't activated. Run `source venv/bin/activate` (Mac) or `venv\Scripts\activate` (Windows) first.

**`Port 8000 already in use`**
→ Something else is using port 8000. Change to `--port 8001` in the uvicorn command and update your browser URL.

**`Port 8081 already in use`** (agent won't start)
→ An old agent worker is still running. Kill it:
```bash
# Mac/Linux
pkill -9 -f "agent.py start"

# Windows (PowerShell)
Get-Process python | Stop-Process
```

**`SSL certificate error`**
→ You're missing the `certifi` package. Run: `pip install certifi`

**Agent starts but calls don't connect**
→ Your `OUTBOUND_TRUNK_ID` is missing. Go to Settings → Vobiz → click "⚡ Create SIP Trunk in LiveKit" first.
