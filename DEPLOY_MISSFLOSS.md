# Miss Floss — Complete Deployment Guide

This guide takes someone with zero context from a fresh GitHub clone to a running
Miss Floss dashboard, both on a personal computer (for testing) and on a VPS (for
production / client use). No prior experience assumed. Follow it top to bottom.

What you are deploying:
- A **dashboard** (FastAPI web app) where doctors log in and see calls, appointments, campaigns.
- A **voice agent worker** (LiveKit + Gemini Live) that actually places and answers phone calls.
- A **Supabase** Postgres database that stores everything.

Two parts must run at the same time: the dashboard (`server.py`) and the agent worker (`agent.py`).

---

## 0. What you need before you start

| Thing | Where to get it | Notes |
|---|---|---|
| The code | `git clone https://github.com/toprmrproducer/missfloss` | Private repo, ask Shreyas for access |
| Python 3.11+ | python.org or `brew install python` | Run `python3 --version` to check |
| A Supabase project | supabase.com (free) | You will copy two values from it |
| A Google AI Studio key | aistudio.google.com/app/apikey | Needs a small billing balance, ~$5 |
| A LiveKit Cloud project | cloud.livekit.io (free tier) | You copy URL + 2 keys |
| A Telnyx account | telnyx.com | For real phone numbers (~$1/number) |

You do not need all of them to just see the dashboard. Supabase + the code is enough
to log in and click around. The phone calling needs LiveKit + Gemini + Telnyx.

---

## PART A — Run on a computer (local, for testing)

### A1. Get the code
```bash
git clone https://github.com/toprmrproducer/missfloss
cd missfloss
```

### A2. Create a Python virtual environment and install dependencies
```bash
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# On Windows:  venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```
This takes 1 to 3 minutes.

### A3. Set up the database (Supabase)
1. Go to supabase.com, create a new project (free). Wait ~2 minutes for it to be ready.
2. In the project, open **SQL Editor**, paste the entire contents of `supabase_schema.sql`
   from this repo, and click **Run**. This creates the tables.
3. Then run this one extra block in the SQL Editor (doctor login + call direction):
   ```sql
   CREATE TABLE IF NOT EXISTS doctors (
     id TEXT PRIMARY KEY,
     email TEXT UNIQUE NOT NULL,
     password_hash TEXT NOT NULL,
     name TEXT NOT NULL,
     role TEXT NOT NULL DEFAULT 'doctor',
     clinic_name TEXT DEFAULT 'Miss Floss',
     created_at TEXT NOT NULL,
     last_login TEXT
   );
   ALTER TABLE doctors DISABLE ROW LEVEL SECURITY;
   GRANT ALL ON doctors TO anon, authenticated, service_role;
   ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS direction TEXT DEFAULT 'outbound';
   ```
4. Get your two Supabase values: **Project Settings → API**.
   - `Project URL` (looks like `https://abcd1234.supabase.co`)
   - `service_role` secret key (long string, keep it private)

### A4. Create the `.env` file
Copy the example and fill it in:
```bash
cp .env.example .env
```
Open `.env` in any text editor and set at minimum:
```env
# Supabase (from step A3)
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_SERVICE_KEY=YOUR_SERVICE_ROLE_KEY

# LiveKit (from cloud.livekit.io -> Settings -> Keys)
LIVEKIT_URL=wss://YOUR-PROJECT.livekit.cloud
LIVEKIT_API_KEY=API...
LIVEKIT_API_SECRET=...
LIVEKIT_SIP_ENDPOINT=YOUR-PROJECT.sip.livekit.cloud

# Google Gemini (from aistudio.google.com/app/apikey)
GOOGLE_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash-native-audio-preview-09-2025

# Auth
SETUP_TOKEN=pick-any-secret-string
COOKIE_SECURE=false        # keep false on localhost
```
You can leave Telnyx blank for now and fill it from the dashboard later (Telnyx Setup tab).

### A5. Start the dashboard
```bash
source venv/bin/activate
export $(grep -v '^#' .env | xargs)        # load .env into the shell (macOS/Linux)
uvicorn server:app --host 0.0.0.0 --port 8100
```
Open **http://localhost:8100** in your browser. You will see the login page.

### A6. Create your first doctor account
On the login page, click **"Create the owner account"**, enter a name, email, and password.
This first account is created automatically (the clinic owner). Adding more doctors later
requires the `SETUP_TOKEN` you set in `.env`.

### A7. Start the voice agent worker (second terminal)
The dashboard runs the website. To actually make calls, the agent worker must run too.
Open a **second terminal**:
```bash
cd missfloss
source venv/bin/activate
export $(grep -v '^#' .env | xargs)
python agent.py start
```
Leave this running. Now go to the dashboard's **Single Call** tab and place a test call,
or use the **Live Link** tab to talk to the agent in your browser (no phone needed).

### A8. Connect a real phone number (Telnyx)
In the dashboard, open the **Telnyx Setup** tab and follow the 5 on-screen steps. That tab
saves your Telnyx credentials and activates the trunk with one click. (Full Telnyx detail
is also in section C below.)

That is the whole local setup. To stop, press `Ctrl+C` in both terminals.

---

## PART B — Deploy on a VPS (production, for clients)

A VPS is a cloud computer that stays on 24/7 so the dashboard and agent are always available.
This uses Docker so you do not install Python by hand. Budget ~30 minutes the first time.

### B1. Get a VPS
- Providers: Hetzner (~€4/mo, best value), DigitalOcean, Vultr (has India region), Linode.
- Pick **Ubuntu 22.04 LTS**, smallest plan with **2 GB RAM** is fine to start.
- You get an IP address and a root password / SSH key.

### B2. Connect to the VPS
```bash
ssh root@YOUR_SERVER_IP
```

### B3. Install Docker
```bash
curl -fsSL https://get.docker.com | sh
docker --version          # confirm it installed
```

### B4. Get the code onto the server
```bash
# Easiest: install git and clone
apt-get update && apt-get install -y git
git clone https://github.com/toprmrproducer/missfloss
cd missfloss
```
(If the repo is private, generate a GitHub token or add a deploy key, or `scp` the folder up.)

### B5. Create the `.env` on the server
Same as step A4, but set `COOKIE_SECURE=true` (you will use HTTPS in production):
```bash
nano .env        # paste your filled-in .env, then Ctrl+O, Enter, Ctrl+X to save
```
Use the **clinic's own** Supabase, LiveKit, Gemini, and Telnyx keys here, not the dev ones.

### B6. Build and launch with Docker Compose
This repo ships a `docker-compose.yml` that runs the dashboard and the agent worker together:
```bash
docker compose up -d --build
```
- `-d` runs it in the background.
- Check it is running: `docker compose ps`
- View logs: `docker compose logs -f`

The dashboard is now live on **http://YOUR_SERVER_IP:8000**.

### B7. (Recommended) Point a domain + HTTPS at it
For `missfloss.ai` or a subdomain like `app.missfloss.ai`:

**Option 1 — Coolify (easiest, has a UI).**
1. Install Coolify on the VPS: `curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash`
2. Open Coolify in your browser, connect the GitHub repo `toprmrproducer/missfloss`.
3. Add your `.env` values in Coolify's environment settings.
4. Set the domain (e.g. `app.missfloss.ai`); Coolify gets a free HTTPS certificate automatically.
5. Deploy. Coolify rebuilds on every git push.

**Option 2 — Nginx + Let's Encrypt (manual).**
1. Point an A record for `app.missfloss.ai` to your server IP at your domain registrar.
2. On the server:
   ```bash
   apt-get install -y nginx certbot python3-certbot-nginx
   ```
3. Create `/etc/nginx/sites-available/missfloss` with a reverse proxy to port 8000:
   ```nginx
   server {
     server_name app.missfloss.ai;
     location / {
       proxy_pass http://localhost:8000;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $remote_addr;
       proxy_set_header X-Forwarded-Proto $scheme;
     }
   }
   ```
4. Enable and get the certificate:
   ```bash
   ln -s /etc/nginx/sites-available/missfloss /etc/nginx/sites-enabled/
   nginx -t && systemctl reload nginx
   certbot --nginx -d app.missfloss.ai
   ```
Now the dashboard is at **https://app.missfloss.ai** with HTTPS. Make sure `.env` has
`COOKIE_SECURE=true` so the login cookie is secure.

### B8. Updating later
```bash
cd missfloss
git pull
docker compose up -d --build      # rebuild with the new code
```
(With Coolify, just `git push` and it redeploys automatically.)

### B9. Keep it healthy
- Logs: `docker compose logs -f`
- Restart: `docker compose restart`
- Stop: `docker compose down`
- The agent worker auto-reconnects to LiveKit. If calls stop working, check
  `docker compose logs` for Gemini credit or Telnyx auth errors.

---

## PART C — Telnyx phone number setup (detailed)

You can do all of this from the dashboard's **Telnyx Setup** tab, but here is the full detail.

1. **Account + number.** Sign up at telnyx.com, add ~$10 balance. Go to
   **Numbers → Search & Buy Numbers**, buy a local number for the clinic's area (~$1).
2. **SIP Connection.** Go to **Voice → SIP Connections → Create**. Name it `Miss Floss`.
   Under **Authentication**, choose **Credentials**, and set a username and password. Save.
3. **Route the number.** **Numbers → My Numbers →** click your number **→ Voice →**
   set Connection to the `Miss Floss` SIP Connection. Save. (This makes inbound calls reach Miss Floss.)
4. **Enter credentials** in the dashboard Telnyx Setup tab (or in `.env`):
   ```env
   TELNYX_SIP_DOMAIN=sip.telnyx.com
   TELNYX_USERNAME=your_sip_username
   TELNYX_PASSWORD=your_sip_password
   TELNYX_OUTBOUND_NUMBER=+14165551234
   ```
5. **Activate.** Click **Activate Outbound Calling** in the dashboard (or
   `POST /api/setup/trunk/telnyx`). For receiving calls, click **Enable Inbound**
   (or `POST /api/setup/trunk/telnyx/inbound`) after pointing the number at
   `LIVEKIT_SIP_ENDPOINT` in step 3.
6. **Test.** Place a call from the **Single Call** tab. If it fails, check the number is
   E.164 (`+countrycode...`) and the SIP username/password match exactly.

---

## Quick reference

| Action | Command |
|---|---|
| Start dashboard (local) | `uvicorn server:app --host 0.0.0.0 --port 8100` |
| Start agent worker (local) | `python agent.py start` |
| Place a test call (CLI) | `python make_call.py --phone +1... --lead "Name"` |
| Run everything (VPS) | `docker compose up -d --build` |
| View logs (VPS) | `docker compose logs -f` |
| Update (VPS) | `git pull && docker compose up -d --build` |

| Key file | What it is |
|---|---|
| `server.py` | The dashboard web app (login, API, UI) |
| `agent.py` | The voice agent worker (calls) |
| `auth.py` | Doctor login / passwords / sessions |
| `.env` | All your secrets and config (never commit this) |
| `ui/index.html` | The dashboard page |
| `ui/login.html` | The login page |
| `supabase_schema.sql` | Database tables |
| `docker-compose.yml` | Runs dashboard + agent together on a VPS |

## Common problems

- **Login page loops / cannot log in:** check `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`
  are correct and the `doctors` table exists (step A3).
- **Agent does not speak on calls:** check `GOOGLE_API_KEY` has billing balance and
  `GEMINI_MODEL=gemini-2.5-flash-native-audio-preview-09-2025`.
- **Telnyx call fails:** number must be E.164; SIP username/password must match the
  Telnyx SIP Connection exactly; run Activate again after changing credentials.
- **Cookie / login not staying on HTTPS:** set `COOKIE_SECURE=true` in production.

That is everything. For a quick local look: clone, `pip install -r requirements.txt`,
fill `.env`, run `uvicorn server:app --port 8100`, open http://localhost:8100.
