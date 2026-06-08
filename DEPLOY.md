# OutboundAI — VPS Docker Deployment Guide

> This guide takes you from zero to a live production deployment on a VPS (Virtual Private Server)  
> in under 30 minutes. No prior Docker experience required.

---

## Table of Contents

1. [What You Need](#1-what-you-need)
2. [Understanding the Docker Setup](#2-understanding-the-docker-setup)
3. [Step 1 — Provision Your VPS](#step-1--provision-your-vps)
4. [Step 2 — Install Docker on the VPS](#step-2--install-docker-on-the-vps)
5. [Step 3 — Upload Your Project](#step-3--upload-your-project)
6. [Step 4 — Configure Your .env on the Server](#step-4--configure-your-env-on-the-server)
7. [Step 5 — Build and Launch](#step-5--build-and-launch)
8. [Step 6 — Set Up a Domain + HTTPS (Recommended)](#step-6--set-up-a-domain--https-recommended)
9. [Step 7 — Set Up Nginx Reverse Proxy](#step-7--set-up-nginx-reverse-proxy)
10. [Step 8 — Enable HTTPS with Let's Encrypt](#step-8--enable-https-with-lets-encrypt)
11. [Day-to-Day Operations](#day-to-day-operations)
12. [Updating Your Deployment](#updating-your-deployment)
13. [Backup Your Data](#backup-your-data)
14. [Scaling for High Volume](#scaling-for-high-volume)
15. [Troubleshooting](#troubleshooting)

---

## 1. What You Need

### VPS Specifications (minimum)

| Spec | Minimum | Recommended |
|---|---|---|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB | 2 GB |
| Storage | 10 GB SSD | 20 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Open port | 8000 (or 80/443) | 80 + 443 |

### Recommended VPS Providers (cheapest to most)

| Provider | Price | Notes |
|---|---|---|
| [Hetzner Cloud](https://hetzner.com/cloud) | ~€4/month | Best value, EU servers |
| [DigitalOcean](https://digitalocean.com) | ~$6/month | Good docs, easy panel |
| [Vultr](https://vultr.com) | ~$6/month | Has India region |
| [Linode/Akamai](https://linode.com) | ~$5/month | Reliable |
| Any Indian VPS | Varies | Lower latency to Vobiz |

### What you need locally
- Terminal (macOS/Linux) or PuTTY/MobaXterm (Windows)
- The project folder on your computer
- Your `.env` file filled in (see [GUIDE.md](GUIDE.md))

---

## 2. Understanding the Docker Setup

When you run `docker compose up`, Docker creates:

```
┌─────────────────────────────────────────────────────────┐
│                    Your VPS Server                       │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────────────┐   │
│  │  outbound-agent  │    │    outbound-server       │   │
│  │  (AI Worker)     │    │    (Dashboard API)       │   │
│  │                  │    │    port 8000             │   │
│  │  python          │    │    uvicorn server:app    │   │
│  │  agent.py start  │    │                          │   │
│  └────────┬─────────┘    └──────────┬───────────────┘   │
│           │                         │                    │
│           └──────────┬──────────────┘                   │
│                      │                                   │
│              ┌───────▼──────────┐                        │
│              │  caller-data     │                        │
│              │  (Docker volume) │                        │
│              │  appointments.db │                        │
│              └──────────────────┘                        │
└─────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
   LiveKit Cloud         Gemini API
   (external)            (external)
```

- Both containers share the **same SQLite database** via a Docker volume
- The agent container connects outbound to LiveKit and Gemini — no inbound ports needed
- The server container exposes port 8000 for the dashboard
- Your `.env` file is read at runtime — **never baked into the Docker image**

---

## Step 1 — Provision Your VPS

### On Hetzner (example — steps are similar on other providers)

1. Go to [console.hetzner.cloud](https://console.hetzner.cloud) → Create Server
2. **Location**: Choose a region close to India for lowest latency (Finland or Singapore)
3. **Image**: Ubuntu 22.04 LTS
4. **Type**: CX22 (2 vCPU, 4 GB RAM) — about €4/month
5. **SSH Key**: Add your public SSH key (or use a password — less secure)
6. Click **Create & Buy**

### Get your server's IP address

Once the server is created, you'll see an IP address like `49.12.34.56`. Copy it.

---

## Step 2 — Install Docker on the VPS

SSH into your server:

```bash
ssh root@YOUR_SERVER_IP
```

Run this single command to install Docker and Docker Compose:

```bash
curl -fsSL https://get.docker.com | sh
```

Verify it worked:

```bash
docker --version
docker compose version
```

You should see something like:
```
Docker version 26.1.0
Docker Compose version v2.27.0
```

---

## Step 3 — Upload Your Project

You have two options. Use whichever you prefer.

---

### Option A — Upload via SCP (copy files directly)

On your **local computer** (not the server), run:

```bash
scp -r "/path/to/Outbound Mass Caller" root@YOUR_SERVER_IP:/opt/outbound-caller
```

Replace `/path/to/Outbound Mass Caller` with the actual path on your computer.

For example on Mac:
```bash
scp -r "/Users/yourname/Desktop/Outbound Mass Caller" root@49.12.34.56:/opt/outbound-caller
```

---

### Option B — Use Git (if you have the project in a Git repo)

On the **server**, run:

```bash
cd /opt
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git outbound-caller
```

---

After upload, on the server:

```bash
cd /opt/outbound-caller
ls
```

You should see: `agent.py  server.py  Dockerfile  docker-compose.yml  ...`

---

## Step 4 — Configure Your .env on the Server

**Never copy your .env from your laptop** — create a fresh one on the server:

```bash
cd /opt/outbound-caller
cp .env.example .env
nano .env
```

This opens the nano text editor. Fill in all your API keys:

```
Use arrow keys to move
Ctrl+O → Save
Ctrl+X → Exit
```

Alternatively, use `vi`:
```bash
vi .env
# Press i to enter insert mode
# Edit the file
# Press Esc, then type :wq to save and exit
```

### Verify your .env looks right

```bash
cat .env
```

Make sure every required variable has a value (not blank).

### Protect your .env file

```bash
chmod 600 .env
```

This makes the file readable only by root — good security practice.

---

## Step 5 — Build and Launch

### Build the Docker image

```bash
cd /opt/outbound-caller
docker compose build
```

This takes 2–5 minutes the first time (downloading Python, installing packages). You'll see lots of output ending with `✓ Built`.

### Initialise the database (first time only)

```bash
docker compose run --rm server python -c "from db import init_db; init_db(); print('DB ready.')"
```

### Sync the Vobiz SIP trunk (first time only)

```bash
docker compose run --rm server python setup_trunk.py
```

You should see: `✅ SIP Trunk updated successfully!`

### Start everything

```bash
docker compose up -d
```

The `-d` flag runs it in the background (detached mode).

### Check that both containers are running

```bash
docker compose ps
```

You should see:
```
NAME               STATUS          PORTS
outbound-agent     Up 2 minutes
outbound-server    Up 2 minutes    0.0.0.0:8000->8000/tcp
```

### Test the dashboard

On your local computer, open: **http://YOUR_SERVER_IP:8000**

You should see the OutboundAI dashboard. 🎉

---

## Step 6 — Set Up a Domain + HTTPS (Recommended)

Running on a raw IP works but HTTPS is more professional and secure. This uses a free domain (or your own).

### If you have a domain

1. Go to your domain registrar (GoDaddy, Namecheap, etc.)
2. Add an **A record** pointing to your server IP:
   ```
   Type: A
   Name: caller  (or @ for root domain)
   Value: YOUR_SERVER_IP
   TTL: 3600
   ```
3. Wait 5–15 minutes for DNS to propagate
4. Test: `ping caller.yourdomain.com` — should resolve to your server IP

---

## Step 7 — Set Up Nginx Reverse Proxy

Nginx sits in front of the dashboard and handles the public-facing traffic.

### Install Nginx

```bash
apt-get update && apt-get install -y nginx
```

### Create the config file

```bash
nano /etc/nginx/sites-available/outbound-caller
```

Paste this (replace `caller.yourdomain.com` with your actual domain or IP):

```nginx
server {
    listen 80;
    server_name caller.yourdomain.com;

    # Forward all requests to the Docker container
    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
    }
}
```

### Enable the config

```bash
ln -s /etc/nginx/sites-available/outbound-caller /etc/nginx/sites-enabled/
nginx -t          # test the config — should say "syntax is ok"
systemctl reload nginx
```

Now the dashboard is accessible at **http://caller.yourdomain.com** (port 80, no `:8000`).

---

## Step 8 — Enable HTTPS with Let's Encrypt

Let's Encrypt gives you a free SSL certificate. This makes your dashboard `https://`.

```bash
# Install certbot
apt-get install -y certbot python3-certbot-nginx

# Get and install the certificate (replace with your domain)
certbot --nginx -d caller.yourdomain.com
```

Certbot will ask:
1. Your email address (for renewal alerts)
2. Agree to terms: `A`
3. Redirect HTTP to HTTPS: `2` (recommended)

After completion, your dashboard is at **https://caller.yourdomain.com** with a valid SSL certificate. Certbot auto-renews every 90 days.

---

## Day-to-Day Operations

### View live logs

```bash
# Both containers
docker compose logs -f

# Just the agent
docker compose logs -f agent

# Just the server
docker compose logs -f server
```

Press `Ctrl+C` to stop following logs.

### Stop everything

```bash
docker compose down
```

### Start everything back up

```bash
docker compose up -d
```

### Restart just one service

```bash
docker compose restart agent
docker compose restart server
```

### Check resource usage

```bash
docker stats
```

Shows CPU, RAM, and network usage per container in real-time.

---

## Updating Your Deployment

When you make changes to the code (locally) and want to deploy the update:

### Step 1 — Upload the changed files to the server

```bash
# From your local machine
scp -r "/Users/yourname/Desktop/Outbound Mass Caller/." root@YOUR_SERVER_IP:/opt/outbound-caller/
```

Or if using Git:
```bash
# On the server
cd /opt/outbound-caller
git pull
```

### Step 2 — Rebuild and restart

```bash
cd /opt/outbound-caller
docker compose build
docker compose up -d
```

Docker will only rebuild what changed — subsequent builds are fast (2–30 seconds).

### Zero-downtime update (server only)

If you only changed server.py or the UI, you can restart just the server:
```bash
docker compose up -d --no-deps --build server
```
The agent keeps running during the server restart, so no calls are dropped.

---

## Backup Your Data

The SQLite database lives in a Docker volume called `caller-data`. Back it up regularly.

### Manual backup

```bash
# Copy the DB file out of the Docker volume
docker run --rm -v outbound-caller_caller-data:/data -v $(pwd):/backup \
    alpine cp /data/appointments.db /backup/appointments-$(date +%Y%m%d).db
```

This creates a timestamped backup file in the current directory.

### Automated daily backup (cron job)

```bash
crontab -e
```

Add this line (backs up daily at 2 AM):
```
0 2 * * * docker run --rm -v outbound-caller_caller-data:/data -v /opt/backups:/backup alpine cp /data/appointments.db /opt/backups/appointments-$(date +\%Y\%m\%d).db
```

### Download backup to your local computer

```bash
# From your local computer
scp root@YOUR_SERVER_IP:/opt/outbound-caller/appointments-20260421.db ~/Desktop/
```

---

## Scaling for High Volume

The default setup handles ~5–10 concurrent calls. For higher volume:

### Scale the agent worker

```bash
docker compose up -d --scale agent=3
```

This runs 3 agent containers, each handling separate calls. LiveKit automatically distributes jobs across all workers with the same `agent_name`.

### Increase to a bigger VPS

On Hetzner, upgrading a CX22 to CX32 (4 vCPU, 8 GB RAM) doubles capacity and costs ~€8/month. No data is lost when resizing.

---

## Troubleshooting

### Container won't start

```bash
docker compose logs agent
docker compose logs server
```

Look for `ERROR` lines — they almost always tell you exactly what's wrong.

---

### "Port 8000 already in use"

```bash
lsof -i :8000
kill -9 PID_NUMBER
```

Or change the port in `docker-compose.yml`:
```yaml
ports:
  - "8080:8000"   # Use port 8080 instead
```

---

### Database errors on startup

```bash
docker compose run --rm server python -c "from db import init_db; init_db(); print('OK')"
```

---

### Agent connects but calls don't go through

Check the agent logs for `OUTBOUND_TRUNK_ID` errors:
```bash
docker compose logs agent | grep -i trunk
```

Re-run the trunk setup:
```bash
docker compose run --rm agent python setup_trunk.py
```

---

### Nginx 502 Bad Gateway

The dashboard container isn't running or is still starting up.

```bash
docker compose ps              # Check status
docker compose up -d server    # Restart it
```

---

### Running out of disk space

```bash
df -h                          # Check disk usage
docker system prune -f         # Remove unused images/containers
```

---

### Reset everything (nuclear option)

```bash
docker compose down -v         # -v removes volumes (DELETES DATABASE)
docker compose up -d
docker compose run --rm server python -c "from db import init_db; init_db()"
```

> ⚠️ `-v` permanently deletes your SQLite database. Download a backup first.

---

## Quick Reference Card

```bash
# Start
docker compose up -d

# Stop  
docker compose down

# Logs
docker compose logs -f

# Restart agent
docker compose restart agent

# Rebuild after code change
docker compose build && docker compose up -d

# Check status
docker compose ps

# Backup database
docker run --rm -v outbound-caller_caller-data:/data -v $(pwd):/backup \
    alpine cp /data/appointments.db /backup/backup.db

# Scale to 3 agent workers
docker compose up -d --scale agent=3
```

---

*Last updated: April 2026*
