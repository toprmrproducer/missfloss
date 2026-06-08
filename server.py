"""
FastAPI backend for the outbound calling dashboard.

Endpoints:
  POST   /api/call                      — Dispatch a single outbound call
  GET    /api/calls                     — Paginated call log
  GET    /api/appointments              — All/filtered appointments
  DELETE /api/appointments/{id}         — Cancel an appointment
  GET    /api/stats                     — Aggregate stats
  GET    /api/prompt                    — Get saved system prompt
  POST   /api/prompt                    — Save system prompt
  DELETE /api/prompt                    — Reset to default
  GET    /api/settings                  — Get all saved API keys/config (secrets masked)
  POST   /api/settings                  — Save API keys/config (BYOK)
  GET    /api/errors                    — Get error log
  DELETE /api/errors                    — Clear error log
  POST   /api/campaigns                 — Create a campaign
  GET    /api/campaigns                 — List all campaigns
  DELETE /api/campaigns/{id}            — Delete a campaign
  POST   /api/campaigns/{id}/run        — Dispatch campaign immediately
  PATCH  /api/campaigns/{id}/status     — Pause / resume a campaign

GET / serves the dashboard from ui/index.html.
"""

import asyncio
import json
import logging
import os
import random
import traceback
import ssl
import certifi
import aiohttp
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Patch ssl.create_default_context to use certifi's CA bundle globally.
_orig_create_default_context = ssl.create_default_context

def _certifi_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, **kwargs):
    if not kwargs.get("cafile") and not kwargs.get("capath") and not kwargs.get("cadata"):
        kwargs["cafile"] = certifi.where()
    return _orig_create_default_context(purpose, **kwargs)

ssl.create_default_context = _certifi_create_default_context

from db import (
    SENSITIVE_KEYS,
    cancel_appointment,
    clear_errors,
    create_campaign,
    delete_campaign,
    get_all_appointments,
    get_all_calls,
    get_all_campaigns,
    get_all_settings,
    get_all_agent_profiles,
    get_agent_profile,
    create_agent_profile,
    update_agent_profile,
    delete_agent_profile,
    set_default_agent_profile,
    get_calls_by_phone,
    get_campaign,
    get_contacts,
    get_errors,
    get_logs,
    get_setting,
    get_stats,
    init_db,
    log_error,
    save_settings,
    set_setting,
    update_call_notes,
    update_campaign_run_stats,
    update_campaign_status,
)
from prompts import DEFAULT_SYSTEM_PROMPT

load_dotenv(".env", override=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

init_db()

# ---------------------------------------------------------------------------
# APScheduler — campaign scheduler
# ---------------------------------------------------------------------------
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    _scheduler = AsyncIOScheduler()
except ImportError:
    _scheduler = None
    logger.warning("APScheduler not installed — campaign scheduling disabled")

app = FastAPI(title="Miss Floss — Dental Voice CRM", version="1.0.0")

# ── Doctor authentication ────────────────────────────────────────────────────
import auth as mf_auth


async def current_doctor(request: Request):
    """Return the logged-in doctor dict, or None."""
    token = request.cookies.get(mf_auth.COOKIE_NAME)
    if not token:
        return None
    email = mf_auth.verify_session_token(token)
    if not email:
        return None
    return await mf_auth.get_doctor_by_email(email)


async def require_doctor(request: Request):
    doc = await current_doctor(request)
    if not doc:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return doc


@app.on_event("startup")
async def _startup():
    if _scheduler:
        _scheduler.start()
        await _reschedule_all_campaigns()


@app.on_event("shutdown")
async def _shutdown():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Helper: DB setting → .env fallback
# ---------------------------------------------------------------------------

async def eff(key: str) -> str:
    """Return the DB-saved value for key, else the .env / os.environ value."""
    val = await get_setting(key, "")
    return val if val else os.getenv(key, "")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CallRequest(BaseModel):
    phone: str
    lead_name: str = "there"
    business_name: str = "our company"
    service_type: str = "our service"
    system_prompt: Optional[str] = None
    agent_profile_id: Optional[str] = None   # override voice/model/prompt from a saved profile


class AgentProfileRequest(BaseModel):
    name: str
    voice: str = "Aoede"
    model: str = "gemini-3.1-flash-live-preview"
    system_prompt: Optional[str] = None
    enabled_tools: str = "[]"
    is_default: bool = False


class PromptRequest(BaseModel):
    prompt: str


class SettingsRequest(BaseModel):
    settings: dict  # {KEY: value, ...}  — empty string = "don't overwrite"


class NotesRequest(BaseModel):
    notes: str


class CampaignRequest(BaseModel):
    name: str
    contacts: list           # [{phone, lead_name, business_name, service_type}, ...]
    schedule_type: str = "once"   # once | daily | weekdays
    schedule_time: str = "09:00"  # HH:MM
    call_delay_seconds: int = 3
    system_prompt: Optional[str] = None
    agent_profile_id: Optional[str] = None  # override voice/model/prompt from saved profile


class StatusRequest(BaseModel):
    status: str  # active | paused


# ---------------------------------------------------------------------------
# Campaign runner helpers
# ---------------------------------------------------------------------------

async def _dispatch_one(lk, lk_api, contact: dict, room_name: str, prompt: Optional[str], profile: Optional[dict] = None) -> bool:
    """Dispatch a single call from a campaign. Returns True on success."""
    try:
        saved_prompt = prompt or (await get_setting("system_prompt", "")) or None
        metadata: dict = {
            "phone_number": contact["phone"],
            "lead_name": contact.get("lead_name", "there"),
            "business_name": contact.get("business_name", "our company"),
            "service_type": contact.get("service_type", "our service"),
            "system_prompt": saved_prompt,
        }
        if profile:
            if not metadata["system_prompt"] and profile.get("system_prompt"):
                metadata["system_prompt"] = profile["system_prompt"]
            if profile.get("voice"):
                metadata["voice_override"] = profile["voice"]
            if profile.get("model"):
                metadata["model_override"] = profile["model"]
            if profile.get("enabled_tools"):
                metadata["tools_override"] = profile["enabled_tools"]
        await lk.agent_dispatch.create_dispatch(
            lk_api.CreateAgentDispatchRequest(
                agent_name="outbound-caller-shreyas",
                room=room_name,
                metadata=json.dumps(metadata),
            )
        )
        return True
    except Exception as exc:
        logger.error("Campaign dispatch error for %s: %s", contact.get("phone"), exc)
        return False


async def _run_campaign(campaign_id: str) -> None:
    """Background task: dispatch all calls for a campaign sequentially."""
    campaign = await get_campaign(campaign_id)
    if not campaign:
        logger.error("Campaign not found: %s", campaign_id)
        return

    contacts = json.loads(campaign.get("contacts_json") or "[]")
    if not contacts:
        logger.warning("Campaign %s has no contacts", campaign_id)
        return

    delay = int(campaign.get("call_delay_seconds") or 3)
    prompt = campaign.get("system_prompt")
    agent_profile_id = campaign.get("agent_profile_id")
    profile = None
    if agent_profile_id:
        from db import get_agent_profile
        profile = await get_agent_profile(agent_profile_id)

    url    = await eff("LIVEKIT_URL")
    key    = await eff("LIVEKIT_API_KEY")
    secret = await eff("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        logger.error("Campaign %s: LiveKit not configured", campaign_id)
        return

    from livekit import api as lk_api_module
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx))

    ok_count = 0
    fail_count = 0
    try:
        lk = lk_api_module.LiveKitAPI(url=url, api_key=key, api_secret=secret, session=session)
        for i, contact in enumerate(contacts):
            phone = contact.get("phone", "")
            if not phone.startswith("+"):
                fail_count += 1
                continue
            room_name = f"camp-{campaign_id[:8]}-{phone.replace('+','')}-{random.randint(100,999)}"
            success = await _dispatch_one(lk, lk_api_module, contact, room_name, prompt, profile)
            if success:
                ok_count += 1
            else:
                fail_count += 1
            if i < len(contacts) - 1:
                await asyncio.sleep(delay)
        await lk.aclose()
    except Exception as exc:
        logger.error("Campaign run error: %s", exc)
    finally:
        await session.close()

    await update_campaign_run_stats(campaign_id, ok_count, fail_count)
    await log_error(
        "server",
        f"Campaign '{campaign.get('name')}' run complete: {ok_count} dispatched, {fail_count} failed",
        level="info",
    )
    logger.info("Campaign %s done: %d dispatched, %d failed", campaign_id, ok_count, fail_count)


async def _reschedule_all_campaigns() -> None:
    """Load all active daily/weekday campaigns and register APScheduler jobs."""
    if not _scheduler:
        return
    try:
        campaigns = await get_all_campaigns()
        for c in campaigns:
            if c["status"] == "active" and c["schedule_type"] in ("daily", "weekdays"):
                _upsert_scheduler_job(c)
    except Exception as exc:
        logger.warning("Could not reschedule campaigns: %s", exc)


def _upsert_scheduler_job(campaign: dict) -> None:
    if not _scheduler:
        return
    job_id = f"campaign_{campaign['id']}"
    # Remove existing job if any
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    if campaign["status"] != "active":
        return

    time_parts = (campaign.get("schedule_time") or "09:00").split(":")
    hour   = int(time_parts[0]) if len(time_parts) > 0 else 9
    minute = int(time_parts[1]) if len(time_parts) > 1 else 0

    if campaign["schedule_type"] == "daily":
        trigger = CronTrigger(hour=hour, minute=minute)
    elif campaign["schedule_type"] == "weekdays":
        trigger = CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute)
    else:
        return

    _scheduler.add_job(
        _run_campaign,
        trigger=trigger,
        args=[campaign["id"]],
        id=job_id,
        replace_existing=True,
    )
    logger.info("Scheduled campaign '%s' (%s) at %02d:%02d", campaign["name"], campaign["schedule_type"], hour, minute)


# ---------------------------------------------------------------------------
# Global exception handler — logs to error_logs table
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _error_logging_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Unhandled error on %s: %s", request.url.path, exc)
        try:
            await log_error(
                source="server",
                message=str(exc),
                detail=f"{request.method} {request.url.path}\n{tb[:1500]}",
            )
        except Exception:
            pass
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# SIP Trunk auto-setup
# ---------------------------------------------------------------------------

def _lk_session():
    """Return an aiohttp session with SSL verification disabled (LiveKit compat)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx))


async def _lk_client(session):
    url    = await eff("LIVEKIT_URL")
    key    = await eff("LIVEKIT_API_KEY")
    secret = await eff("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        raise HTTPException(400, "LiveKit credentials not configured — go to Settings first.")
    from livekit import api as lk_api_module
    return lk_api_module.LiveKitAPI(url=url, api_key=key, api_secret=secret, session=session), lk_api_module


@app.post("/api/setup/trunk")
async def api_setup_trunk():
    """
    Create a LiveKit SIP outbound trunk using saved VoiceLink credentials,
    then save the resulting trunk ID back to settings.
    Call this once after configuring VoiceLink settings.
    """
    sip_domain = await eff("VOICELINK_SIP_DOMAIN")
    username   = await eff("VOICELINK_USERNAME")
    password   = await eff("VOICELINK_PASSWORD")

    if not all([sip_domain, username, password]):
        raise HTTPException(400, "VoiceLink credentials incomplete — set SIP Domain, Username, and Password first.")

    numbers_raw = []
    for key in ["VOICELINK_OUTBOUND_NUMBER", "VOICELINK_DID_2",
                "VOICELINK_DID_3", "VOICELINK_DID_4"]:
        n = await eff(key)
        if n and n.startswith("+"):
            numbers_raw.append(n)
    if not numbers_raw:
        raise HTTPException(400, "No valid VoiceLink DID numbers configured — "
                            "set VOICELINK_OUTBOUND_NUMBER (and optionally DID_2/3/4) first.")

    session = _lk_session()
    try:
        lk, lk_api = await _lk_client(session)
        trunk = await lk.sip.create_sip_outbound_trunk(
            lk_api.CreateSIPOutboundTrunkRequest(
                trunk=lk_api.SIPOutboundTrunkInfo(
                    name="VoiceLink Outbound Trunk",
                    address=sip_domain,
                    auth_username=username,
                    auth_password=password,
                    numbers=numbers_raw,
                )
            )
        )
        trunk_id = trunk.sip_trunk_id
        await set_setting("OUTBOUND_TRUNK_ID", trunk_id)
        logger.info("SIP trunk created: %s", trunk_id)
        await log_error("server", f"SIP trunk auto-created: {trunk_id}", level="info")
        return {"status": "created", "trunk_id": trunk_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Trunk setup failed: %s", exc)
        await log_error("server", f"Trunk setup failed: {exc}", level="error")
        raise HTTPException(500, str(exc))
    finally:
        await session.close()


@app.post("/api/setup/trunk/telnyx")
async def api_setup_trunk_telnyx():
    """
    Create a LiveKit SIP outbound trunk using saved Telnyx credentials.
    Telnyx is configured via a SIP Connection (Credentials auth) in the
    Telnyx portal. Domain defaults to sip.telnyx.com.
    Saves the resulting trunk ID to OUTBOUND_TRUNK_ID.
    """
    sip_domain = (await eff("TELNYX_SIP_DOMAIN")) or "sip.telnyx.com"
    username   = await eff("TELNYX_USERNAME")
    password   = await eff("TELNYX_PASSWORD")

    if not all([username, password]):
        raise HTTPException(400, "Telnyx credentials incomplete. Set TELNYX_USERNAME and TELNYX_PASSWORD (SIP Connection credentials) first.")

    numbers_raw = []
    for key in ["TELNYX_OUTBOUND_NUMBER", "TELNYX_DID_2",
                "TELNYX_DID_3", "TELNYX_DID_4"]:
        n = await eff(key)
        if n and n.startswith("+"):
            numbers_raw.append(n)
    if not numbers_raw:
        raise HTTPException(400, "No valid Telnyx DID numbers configured. Set TELNYX_OUTBOUND_NUMBER (E.164, +1...) first.")

    session = _lk_session()
    try:
        lk, lk_api = await _lk_client(session)
        trunk = await lk.sip.create_sip_outbound_trunk(
            lk_api.CreateSIPOutboundTrunkRequest(
                trunk=lk_api.SIPOutboundTrunkInfo(
                    name="Telnyx Outbound Trunk",
                    address=sip_domain,
                    transport=1,  # UDP — most reliable for PSTN RTP
                    auth_username=username,
                    auth_password=password,
                    numbers=numbers_raw,
                )
            )
        )
        trunk_id = trunk.sip_trunk_id
        await set_setting("OUTBOUND_TRUNK_ID", trunk_id)
        await set_setting("ACTIVE_TELEPHONY_PROVIDER", "telnyx")
        logger.info("Telnyx SIP trunk created: %s", trunk_id)
        await log_error("server", f"Telnyx SIP trunk auto-created: {trunk_id}", level="info")
        return {"status": "created", "trunk_id": trunk_id, "provider": "telnyx", "numbers": numbers_raw}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Telnyx trunk setup failed: %s", exc)
        await log_error("server", f"Telnyx trunk setup failed: {exc}", level="error")
        raise HTTPException(500, str(exc))
    finally:
        await session.close()


@app.post("/api/setup/trunk/telnyx/inbound")
async def api_setup_trunk_telnyx_inbound():
    """
    Create a LiveKit SIP INBOUND trunk for Telnyx DIDs + a dispatch rule so
    inbound calls to Telnyx numbers route to the agent.
    Point your Telnyx number's Voice -> SIP Connection / FQDN at the LiveKit
    SIP URI (LIVEKIT_SIP_ENDPOINT) before calling this.
    """
    numbers_raw = []
    for key in ["TELNYX_OUTBOUND_NUMBER", "TELNYX_DID_2",
                "TELNYX_DID_3", "TELNYX_DID_4"]:
        n = await eff(key)
        if n and n.startswith("+"):
            numbers_raw.append(n)
    if not numbers_raw:
        raise HTTPException(400, "No valid Telnyx DID numbers configured.")

    session = _lk_session()
    try:
        lk, lk_api = await _lk_client(session)
        trunk = await lk.sip.create_sip_inbound_trunk(
            lk_api.CreateSIPInboundTrunkRequest(
                trunk=lk_api.SIPInboundTrunkInfo(
                    name="Telnyx Inbound Trunk",
                    numbers=numbers_raw,
                )
            )
        )
        trunk_id = trunk.sip_trunk_id
        await set_setting("INBOUND_TRUNK_ID", trunk_id)

        rule = await lk.sip.create_sip_dispatch_rule(
            lk_api.CreateSIPDispatchRuleRequest(
                rule=lk_api.SIPDispatchRule(
                    dispatch_rule_individual=lk_api.SIPDispatchRuleIndividual(
                        room_prefix="inbound-",
                    )
                ),
                trunk_ids=[trunk_id],
                agent_name="outbound-caller-shreyas",
            )
        )
        rule_id = rule.sip_dispatch_rule_id
        await set_setting("INBOUND_DISPATCH_RULE_ID", rule_id)
        await log_error("server", f"Telnyx inbound trunk + rule created: {trunk_id} / {rule_id}", level="info")
        return {"status": "created", "trunk_id": trunk_id, "dispatch_rule_id": rule_id, "numbers": numbers_raw}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Telnyx inbound setup failed: %s", exc)
        await log_error("server", f"Telnyx inbound setup failed: {exc}", level="error")
        raise HTTPException(500, str(exc))
    finally:
        await session.close()


@app.get("/api/setup/trunk")
async def api_list_trunks():
    """List existing SIP outbound trunks in this LiveKit project."""
    session = _lk_session()
    try:
        lk, lk_api = await _lk_client(session)
        trunks = await lk.sip.list_sip_outbound_trunk(lk_api.ListSIPOutboundTrunkRequest())
        return {"trunks": [{"id": t.sip_trunk_id, "name": t.name, "address": t.address} for t in (trunks.items or [])]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    finally:
        await session.close()


@app.post("/api/setup/inbound-trunk")
async def api_setup_inbound_trunk():
    """
    Create a LiveKit SIP INBOUND trunk using the configured VoiceLink DIDs.
    This allows VoiceLink to route incoming calls to your LiveKit room.
    You must configure VoiceLink to send calls to your LiveKit SIP URI first.
    """
    numbers_raw = []
    for key in ["VOICELINK_OUTBOUND_NUMBER", "VOICELINK_DID_2",
                "VOICELINK_DID_3", "VOICELINK_DID_4"]:
        n = await eff(key)
        if n and n.startswith("+"):
            numbers_raw.append(n)

    if not numbers_raw:
        raise HTTPException(400, "No VoiceLink DID numbers configured.")

    session = _lk_session()
    try:
        lk, lk_api = await _lk_client(session)
        trunk = await lk.sip.create_sip_inbound_trunk(
            lk_api.CreateSIPInboundTrunkRequest(
                trunk=lk_api.SIPInboundTrunkInfo(
                    name="VoiceLink Inbound Trunk",
                    numbers=numbers_raw,
                )
            )
        )
        trunk_id = trunk.sip_trunk_id
        await set_setting("INBOUND_TRUNK_ID", trunk_id)
        logger.info("Inbound SIP trunk created: %s", trunk_id)
        await log_error("server", f"Inbound SIP trunk created: {trunk_id}", level="info")
        return {"status": "created", "trunk_id": trunk_id, "numbers": numbers_raw}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Inbound trunk setup failed: %s", exc)
        await log_error("server", f"Inbound trunk setup failed: {exc}", level="error")
        raise HTTPException(500, str(exc))
    finally:
        await session.close()


@app.post("/api/setup/dispatch-rule")
async def api_setup_dispatch_rule():
    """
    Create a LiveKit dispatch rule that routes every inbound call into
    a unique room (prefix 'inbound-') and triggers the outbound-caller agent.
    Call this once after creating the inbound trunk.
    """
    session = _lk_session()
    try:
        lk, lk_api = await _lk_client(session)
        rule = await lk.sip.create_sip_dispatch_rule(
            lk_api.CreateSIPDispatchRuleRequest(
                rule=lk_api.SIPDispatchRule(
                    dispatch_rule_individual=lk_api.SIPDispatchRuleIndividual(
                        room_prefix="inbound-",
                    )
                ),
                name="VoiceLink Inbound Dispatch",
                agent_name="outbound-caller-shreyas",
            )
        )
        rule_id = rule.sip_dispatch_rule_id
        await set_setting("INBOUND_DISPATCH_RULE_ID", rule_id)
        logger.info("SIP dispatch rule created: %s", rule_id)
        await log_error("server", f"SIP dispatch rule created: {rule_id}", level="info")
        return {"status": "created", "rule_id": rule_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Dispatch rule setup failed: %s", exc)
        await log_error("server", f"Dispatch rule setup failed: {exc}", level="error")
        raise HTTPException(500, str(exc))
    finally:
        await session.close()


@app.get("/api/setup/inbound-trunk")
async def api_list_inbound_trunks():
    """List existing inbound SIP trunks."""
    session = _lk_session()
    try:
        lk, lk_api = await _lk_client(session)
        trunks = await lk.sip.list_sip_inbound_trunk(lk_api.ListSIPInboundTrunkRequest())
        return {
            "trunks": [
                {"id": t.sip_trunk_id, "name": t.name, "numbers": list(t.numbers)}
                for t in (trunks.items or [])
            ]
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Call dispatch
# ---------------------------------------------------------------------------

@app.post("/api/call")
async def api_trigger_call(req: CallRequest):
    """Dispatch a single outbound call via LiveKit agent dispatch."""
    if not req.phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Phone must start with '+' (E.164 format)")

    # Credentials: DB setting wins, .env is fallback
    url    = await eff("LIVEKIT_URL")
    key    = await eff("LIVEKIT_API_KEY")
    secret = await eff("LIVEKIT_API_SECRET")

    if not (url and key and secret):
        raise HTTPException(
            status_code=400,
            detail="LiveKit credentials not configured. Go to ⚙️ Settings and add your keys.",
        )

    session = _lk_session()
    try:
        lk, lk_api = await _lk_client(session)
        room_name = f"call-{req.phone.replace('+', '')}-{random.randint(1000, 9999)}"

        effective_prompt = req.system_prompt
        effective_voice = None
        effective_model = None
        effective_tools = None

        # Apply agent profile overrides if specified
        if req.agent_profile_id:
            profile = await get_agent_profile(req.agent_profile_id)
            if profile:
                if not effective_prompt and profile.get("system_prompt"):
                    effective_prompt = profile["system_prompt"]
                effective_voice = profile.get("voice")
                effective_model = profile.get("model")
                effective_tools = profile.get("enabled_tools")

        if not effective_prompt:
            saved = await get_setting("system_prompt", "")
            effective_prompt = saved if saved else None

        metadata = {
            "phone_number": req.phone,
            "lead_name": req.lead_name,
            "business_name": req.business_name,
            "service_type": req.service_type,
            "system_prompt": effective_prompt,
        }
        if effective_voice:
            metadata["voice_override"] = effective_voice
        if effective_model:
            metadata["model_override"] = effective_model
        if effective_tools:
            metadata["tools_override"] = effective_tools

        dispatch = await lk.agent_dispatch.create_dispatch(
            lk_api.CreateAgentDispatchRequest(
                agent_name="outbound-caller-shreyas",
                room=room_name,
                metadata=json.dumps(metadata),
            )
        )
        await lk.aclose()

        return {
            "status": "dispatched",
            "room_name": room_name,
            "job_id": dispatch.id,
            "phone": req.phone,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Dispatch error: %s", exc)
        await log_error("server", f"Dispatch failed for {req.phone}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Call logs, appointments, stats
# ---------------------------------------------------------------------------

@app.get("/api/calls")
async def api_get_calls(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    rows = await get_all_calls(page=page, limit=limit)
    return {"page": page, "limit": limit, "data": rows}


@app.get("/api/appointments")
async def api_get_appointments(date: Optional[str] = None):
    rows = await get_all_appointments(date_filter=date)
    return {"data": rows}


@app.delete("/api/appointments/{appointment_id}")
async def api_cancel_appointment(appointment_id: str):
    ok = await cancel_appointment(appointment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Appointment not found or already cancelled")
    return {"status": "cancelled", "id": appointment_id}


@app.get("/api/stats")
async def api_get_stats():
    return await get_stats()


# ---------------------------------------------------------------------------
# CRM
# ---------------------------------------------------------------------------

@app.get("/api/crm")
async def api_get_contacts():
    return {"data": await get_contacts()}


@app.get("/api/crm/calls")
async def api_get_contact_calls(phone: str = Query(...)):
    return {"data": await get_calls_by_phone(phone)}


@app.patch("/api/calls/{call_id}/notes")
async def api_update_notes(call_id: str, req: NotesRequest):
    ok = await update_call_notes(call_id, req.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Call not found")
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@app.post("/api/campaigns")
async def api_create_campaign(req: CampaignRequest):
    """Create a new outbound campaign."""
    if not req.contacts:
        raise HTTPException(400, "contacts list cannot be empty")
    if req.schedule_type not in ("once", "daily", "weekdays"):
        raise HTTPException(400, "schedule_type must be one of: once, daily, weekdays")

    contacts_json = json.dumps(req.contacts)
    campaign_id = await create_campaign(
        name=req.name,
        contacts_json=contacts_json,
        schedule_type=req.schedule_type,
        schedule_time=req.schedule_time,
        call_delay_seconds=req.call_delay_seconds,
        system_prompt=req.system_prompt,
        agent_profile_id=req.agent_profile_id,
    )

    campaign = await get_campaign(campaign_id)

    if req.schedule_type == "once":
        # Run immediately as a background task
        asyncio.create_task(_run_campaign(campaign_id))
    else:
        # Register scheduler job for daily/weekday campaigns
        if campaign:
            _upsert_scheduler_job(campaign)

    return {"status": "created", "id": campaign_id, "will_run": req.schedule_type == "once"}


@app.get("/api/campaigns")
async def api_list_campaigns():
    campaigns = await get_all_campaigns()
    return {"data": campaigns}


@app.delete("/api/campaigns/{campaign_id}")
async def api_delete_campaign(campaign_id: str):
    # Remove from scheduler if present
    if _scheduler:
        job_id = f"campaign_{campaign_id}"
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
    ok = await delete_campaign(campaign_id)
    if not ok:
        raise HTTPException(404, "Campaign not found")
    return {"status": "deleted"}


@app.post("/api/campaigns/{campaign_id}/run")
async def api_run_campaign(campaign_id: str):
    """Dispatch a campaign immediately (run now), regardless of its schedule."""
    campaign = await get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    asyncio.create_task(_run_campaign(campaign_id))
    return {"status": "running", "contacts": len(json.loads(campaign.get("contacts_json") or "[]"))}


@app.patch("/api/campaigns/{campaign_id}/status")
async def api_campaign_status(campaign_id: str, req: StatusRequest):
    """Pause or resume a scheduled campaign."""
    if req.status not in ("active", "paused"):
        raise HTTPException(400, "status must be 'active' or 'paused'")
    ok = await update_campaign_status(campaign_id, req.status)
    if not ok:
        raise HTTPException(404, "Campaign not found")

    campaign = await get_campaign(campaign_id)
    if campaign:
        _upsert_scheduler_job(campaign)  # re-register or remove scheduler job

    return {"status": req.status}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

@app.get("/api/prompt")
async def api_get_prompt():
    saved = await get_setting("system_prompt", "")
    return {"prompt": saved if saved else DEFAULT_SYSTEM_PROMPT, "is_custom": bool(saved)}


@app.post("/api/prompt")
async def api_save_prompt(req: PromptRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    await set_setting("system_prompt", req.prompt.strip())
    return {"status": "saved"}


@app.delete("/api/prompt")
async def api_reset_prompt():
    await set_setting("system_prompt", "")
    return {"status": "reset", "prompt": DEFAULT_SYSTEM_PROMPT}


# ---------------------------------------------------------------------------
# BYOK Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def api_get_settings():
    """
    Return all saved settings.
    Sensitive keys (API secrets, passwords) come back as
    {"value": "", "configured": true} — the raw secret is never sent to the browser.
    """
    return await get_all_settings()


@app.post("/api/settings")
async def api_save_settings(req: SettingsRequest):
    """
    Save a batch of settings.
    Only whitelisted keys are accepted. Empty values are skipped (won't wipe existing secrets).
    """
    ALLOWED_KEYS = {
        "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
        "GOOGLE_API_KEY", "GEMINI_MODEL", "GEMINI_TTS_VOICE", "USE_GEMINI_REALTIME",
        "VOICELINK_SIP_DOMAIN", "VOICELINK_USERNAME", "VOICELINK_PASSWORD",
        "VOICELINK_OUTBOUND_NUMBER", "VOICELINK_DID_2", "VOICELINK_DID_3", "VOICELINK_DID_4",
        "TELNYX_SIP_DOMAIN", "TELNYX_USERNAME", "TELNYX_PASSWORD",
        "TELNYX_OUTBOUND_NUMBER", "TELNYX_DID_2", "TELNYX_DID_3", "TELNYX_DID_4",
        "ACTIVE_TELEPHONY_PROVIDER",
        "OUTBOUND_TRUNK_ID", "INBOUND_TRUNK_ID", "INBOUND_DISPATCH_RULE_ID",
        "LIVEKIT_SIP_ENDPOINT", "DEFAULT_TRANSFER_NUMBER",
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_BUCKET_NAME", "AWS_REGION", "S3_ENDPOINT",
        "CALCOM_API_KEY", "CALCOM_EVENT_TYPE_ID", "CALCOM_TIMEZONE",
        "ENABLED_TOOLS", "DEEPGRAM_API_KEY",
    }
    filtered = {k: v for k, v in req.settings.items() if k in ALLOWED_KEYS}
    if not filtered:
        raise HTTPException(status_code=400, detail="No valid settings keys provided")
    await save_settings(filtered)
    return {"status": "saved", "keys_updated": list(filtered.keys())}


# ---------------------------------------------------------------------------
# Logs (all levels) + Errors (alias for backward compat)
# ---------------------------------------------------------------------------

@app.get("/api/logs")
async def api_get_logs(
    level: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    rows = await get_logs(level=level, source=source, limit=limit)
    return {"data": rows}


@app.delete("/api/logs")
async def api_clear_logs():
    await clear_errors()
    return {"status": "cleared"}


@app.get("/api/errors")
async def api_get_errors(limit: int = Query(100, ge=1, le=500)):
    rows = await get_errors(limit=limit)
    return {"data": rows}


@app.delete("/api/errors")
async def api_clear_errors():
    await clear_errors()
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# Agent Profiles
# ---------------------------------------------------------------------------

@app.get("/api/agent-profiles")
async def api_list_agent_profiles():
    try:
        profiles = await get_all_agent_profiles()
        return profiles
    except Exception as exc:
        logger.error("Error listing agent profiles: %s", exc)
        await log_error("server", f"Error listing agent profiles: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/agent-profiles")
async def api_create_agent_profile(req: AgentProfileRequest):
    try:
        profile_id = await create_agent_profile(
            name=req.name,
            voice=req.voice,
            model=req.model,
            system_prompt=req.system_prompt,
            enabled_tools=req.enabled_tools,
            is_default=req.is_default,
        )
        return {"id": profile_id, "status": "created"}
    except Exception as exc:
        logger.error("Error creating agent profile: %s", exc)
        await log_error("server", f"Error creating agent profile: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/agent-profiles/{profile_id}")
async def api_get_agent_profile(profile_id: str):
    try:
        profile = await get_agent_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.put("/api/agent-profiles/{profile_id}")
async def api_update_agent_profile(profile_id: str, req: AgentProfileRequest):
    try:
        updates = {
            "name": req.name,
            "voice": req.voice,
            "model": req.model,
            "system_prompt": req.system_prompt,
            "enabled_tools": req.enabled_tools,
            "is_default": 1 if req.is_default else 0,
        }
        ok = await update_agent_profile(profile_id, updates)
        if not ok:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {"status": "updated"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/agent-profiles/{profile_id}")
async def api_delete_agent_profile(profile_id: str):
    try:
        ok = await delete_agent_profile(profile_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/agent-profiles/{profile_id}/set-default")
async def api_set_default_profile(profile_id: str):
    try:
        await set_default_agent_profile(profile_id)
        return {"status": "default set"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Web call (browser test link) — no phone number, browser talks to agent
# ---------------------------------------------------------------------------

@app.post("/api/web-call/start")
async def web_call_start():
    """Create a LiveKit room, dispatch the agent, return browser join token."""
    from livekit import api as lk_api_module
    import uuid
    from datetime import timedelta

    url    = await eff("LIVEKIT_URL")
    key    = await eff("LIVEKIT_API_KEY")
    secret = await eff("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        raise HTTPException(400, "LiveKit credentials not configured.")

    room_name = f"web-call-{uuid.uuid4().hex[:10]}"
    participant_identity = f"web-{uuid.uuid4().hex[:8]}"

    saved_prompt = (await get_setting("system_prompt", "")) or None
    metadata = {
        "phone_number": None,
        "lead_name": "Web Visitor",
        "business_name": "RapidX AI",
        "service_type": "demo",
        "system_prompt": saved_prompt,
    }

    lk = lk_api_module.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        await lk.agent_dispatch.create_dispatch(
            lk_api_module.CreateAgentDispatchRequest(
                agent_name="outbound-caller-shreyas",
                room=room_name,
                metadata=json.dumps(metadata),
            )
        )
    finally:
        await lk.aclose()

    token = (
        lk_api_module.AccessToken(key, secret)
        .with_identity(participant_identity)
        .with_name("Web Visitor")
        .with_grants(
            lk_api_module.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
        .with_ttl(timedelta(minutes=30))
        .to_jwt()
    )
    return {"room": room_name, "token": token, "url": url, "identity": participant_identity}


@app.get("/api/public-url")
async def api_public_url(request: Request):
    """Return the public URL of this server (cloudflared tunnel) or fall back to request host."""
    f = Path(__file__).parent / ".public-url"
    if f.exists():
        url = f.read_text().strip()
        if url:
            return {"url": url}
    return {"url": str(request.base_url).rstrip("/")}


@app.get("/talk", response_class=HTMLResponse)
async def serve_talk():
    page = Path(__file__).parent / "ui" / "talk.html"
    if not page.exists():
        return HTMLResponse("<h1>talk.html missing</h1>", status_code=404)
    return HTMLResponse(page.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Serve UI
# ---------------------------------------------------------------------------

UI_DIR = Path(__file__).parent / "ui"


# ── Auth endpoints ───────────────────────────────────────────────────────────

class _LoginReq(BaseModel):
    email: str
    password: str


class _RegisterReq(BaseModel):
    email: str
    password: str
    name: str
    setup_token: Optional[str] = None


@app.post("/api/auth/login")
async def api_login(req: _LoginReq, response: Response):
    doc = await mf_auth.authenticate(req.email, req.password)
    if not doc:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = mf_auth.make_session_token(doc["email"])
    response.set_cookie(
        key=mf_auth.COOKIE_NAME, value=token,
        max_age=mf_auth.SESSION_TTL, httponly=True, samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    )
    return {"status": "ok", "doctor": {"email": doc["email"], "name": doc["name"], "role": doc.get("role")}}


@app.post("/api/auth/logout")
async def api_logout(response: Response):
    response.delete_cookie(mf_auth.COOKIE_NAME)
    return {"status": "ok"}


@app.get("/api/auth/me")
async def api_me(request: Request):
    doc = await current_doctor(request)
    if not doc:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"email": doc["email"], "name": doc["name"], "role": doc.get("role"), "clinic_name": doc.get("clinic_name")}


@app.post("/api/auth/register")
async def api_register(req: _RegisterReq):
    """
    Create a doctor account. The FIRST doctor can self-register (clinic owner
    onboarding). After that, a SETUP_TOKEN (env) is required to add more.
    """
    existing = await mf_auth.count_doctors()
    if existing > 0:
        required = os.getenv("SETUP_TOKEN", "")
        if not required or req.setup_token != required:
            raise HTTPException(status_code=403, detail="Account creation is locked. Ask the clinic admin for a setup token.")
    try:
        doc = await mf_auth.create_doctor(req.email, req.password, req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "created", "doctor": doc}


# ── UI serving (gated) ───────────────────────────────────────────────────────

if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

    @app.get("/login", response_class=HTMLResponse)
    async def serve_login():
        page = UI_DIR / "login.html"
        if not page.exists():
            return HTMLResponse("<h1>Login page missing</h1>", status_code=404)
        return HTMLResponse(page.read_text(encoding="utf-8"))

    @app.get("/", response_class=HTMLResponse)
    async def serve_dashboard(request: Request):
        doc = await current_doctor(request)
        if not doc:
            return RedirectResponse(url="/login", status_code=302)
        index = UI_DIR / "index.html"
        if not index.exists():
            return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)
        return HTMLResponse(index.read_text(encoding="utf-8"))
else:
    @app.get("/")
    async def no_ui():
        return {"message": "UI not found. Create the ui/ directory with index.html."}
