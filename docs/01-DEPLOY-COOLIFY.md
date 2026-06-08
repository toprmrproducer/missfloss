# 🚀 Deploy on Coolify

Coolify is a self-hosted platform that runs your app in Docker on any VPS. This is the recommended production deployment.

---

## Prerequisites

- A VPS with at least **2 GB RAM, 2 vCPU** (Hetzner CX21, DigitalOcean Basic, etc.)
- Docker installed on the VPS
- Coolify installed: [coolify.io/docs/installation](https://coolify.io/docs/installation)
- Your GitHub repo forked or cloned to your account

---

## Step-by-step deployment

### 1. Create a new resource in Coolify

1. Open Coolify dashboard → **Projects** → **+ New Resource**
2. Select **GitHub** (connect your GitHub account if prompted)
3. Choose your `outbound` repository
4. Select branch: `main`
5. Build pack: **Dockerfile** (auto-detected)

### 2. Set the environment variables

In Coolify → your service → **Environment Variables**, add every variable from `docs/02-ENV-VARIABLES.md`.

> **Important:** Add ALL variables before the first deploy. The app will fail to start without at minimum `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, and `GOOGLE_API_KEY`.

### 3. Set the port

- **Port**: `8000`
- Coolify will expose this port and give you a public URL

### 4. Deploy

Click **Deploy**. Watch the build logs — the first build takes 3–5 minutes.

Successful startup looks like:
```
🚀 Starting Outbound Mass Caller...
✅ Supabase connected
🌐 Starting FastAPI server on port 8000...
🤖 Starting LiveKit agent worker...
{"message": "registered worker", "agent_name": "outbound-caller", ...}
```

### 5. Access the dashboard

Open the URL Coolify gave you (e.g. `https://outbound.yourdomain.com`).

---

## Updating after code changes

Every time you push to `main`:
1. Coolify auto-deploys (if webhook is set up) — OR
2. Click **Redeploy** in Coolify manually

> After changing environment variables in Coolify, you **must redeploy** for the changes to take effect. The app reads env vars only at startup.

---

## Resource requirements

| Traffic | RAM | CPU |
|---|---|---|
| 1–5 concurrent calls | 1 GB | 1 vCPU |
| 5–20 concurrent calls | 2 GB | 2 vCPU |
| 20+ concurrent calls | 4 GB+ | 4 vCPU+ |

---

## Troubleshooting deploy issues

**Build fails with "pip install" errors**
→ Check your `requirements.txt`. If a package version changed, try removing the pinned version.

**App starts but dashboard is blank**
→ Check the Coolify logs for "Supabase connected". If you see a Supabase error, your `SUPABASE_URL` or `SUPABASE_SERVICE_KEY` is wrong.

**"registered worker" never appears in logs**
→ `LIVEKIT_URL`, `LIVEKIT_API_KEY`, or `LIVEKIT_API_SECRET` is missing or wrong.

**Port already in use**
→ Coolify assigned the wrong port. Explicitly set port `8000` in the service settings.

---

## Run locally (Mac / Windows)

See `docs/02-RUN-LOCALLY.md`.
