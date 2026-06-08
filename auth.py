"""
Doctor authentication for the Miss Floss dashboard.

Simple, dependency-light auth:
  - Passwords hashed with PBKDF2-HMAC-SHA256 (stdlib hashlib).
  - Session is an HMAC-signed cookie (no server-side session store needed).
  - Doctors live in the `doctors` table (Supabase).

At delivery the clinic gets its own Supabase; swap SUPABASE_URL / key in .env.
"""
import os
import hmac
import json
import time
import base64
import hashlib
import secrets as _secrets
from datetime import datetime, timezone

from db import _adb, _default

COOKIE_NAME = "mf_session"
SESSION_TTL = 60 * 60 * 24 * 7  # 7 days


def _signing_key() -> bytes:
    # Reuse the LiveKit secret as the signing key so there is no extra secret to manage.
    key = _default("LIVEKIT_API_SECRET") or _default("SUPABASE_SERVICE_KEY") or "miss-floss-dev-key"
    return key.encode("utf-8")


# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = _secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2$200000${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ── Signed session token ─────────────────────────────────────────────────────

def make_session_token(email: str) -> str:
    payload = {"email": email, "exp": int(time.time()) + SESSION_TTL}
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_signing_key(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_session_token(token: str):
    try:
        raw, sig = token.split(".")
        expected = hmac.new(_signing_key(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("email")
    except Exception:
        return None


# ── Doctor records ───────────────────────────────────────────────────────────

async def get_doctor_by_email(email: str):
    db = await _adb()
    res = await db.table("doctors").select("*").eq("email", email.lower().strip()).limit(1).execute()
    rows = res.data or []
    return rows[0] if rows else None


async def create_doctor(email: str, password: str, name: str, role: str = "doctor",
                        clinic_name: str = "Miss Floss") -> dict:
    db = await _adb()
    email = email.lower().strip()
    existing = await get_doctor_by_email(email)
    if existing:
        raise ValueError("A doctor with that email already exists.")
    rec = {
        "id": _secrets.token_hex(12),
        "email": email,
        "password_hash": hash_password(password),
        "name": name.strip() or email,
        "role": role,
        "clinic_name": clinic_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.table("doctors").insert(rec).execute()
    rec.pop("password_hash", None)
    return rec


async def authenticate(email: str, password: str):
    doc = await get_doctor_by_email(email)
    if not doc:
        return None
    if not verify_password(password, doc.get("password_hash", "")):
        return None
    db = await _adb()
    await db.table("doctors").update(
        {"last_login": datetime.now(timezone.utc).isoformat()}
    ).eq("id", doc["id"]).execute()
    doc.pop("password_hash", None)
    return doc


async def count_doctors() -> int:
    db = await _adb()
    res = await db.table("doctors").select("id").execute()
    return len(res.data or [])
