# ─────────────────────────────────────────────────────────────────────────────
# Outbound AI Caller — Dockerfile
# Used for both the agent worker and the dashboard server (CMD is overridden
# per-service in docker-compose.yml).
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# System libraries needed by audio/ML packages
# libgomp1     → OpenMP, required by onnxruntime (silero VAD, noise cancellation)
# libglib2.0-0 → glib, required by some audio backends
# libsndfile1  → audio file I/O
# curl         → used by livekit health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Persistent data directory (mounted as a Docker volume)
RUN mkdir -p /data

# The DB path is set via DB_PATH env var in docker-compose.yml
ENV DB_PATH=/data/appointments.db

# Expose dashboard port
EXPOSE 8000

# Start both the FastAPI dashboard server and the LiveKit agent worker
CMD ["sh", "start.sh"]
