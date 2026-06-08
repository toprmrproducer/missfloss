# =============================================================================
# OUTBOUND AI APPOINTMENT BOOKING AGENT
# =============================================================================
#
# ARCHITECTURE DECISION:
#   PRIMARY PATH  → google.realtime.RealtimeModel (livekit-plugins-google >= 1.0)
#     Wraps Google Gemini Live API (gemini-2.0-flash-live-001).
#     Audio-in → Gemini Live → Audio-out in a single WebSocket session.
#     This collapses STT + LLM + TTS into ONE API call — no Deepgram, no
#     separate TTS needed. Cheapest possible path.
#
#   FALLBACK PATH → google.beta.realtime.RealtimeModel (older plugin versions)
#     Identical semantics; the module was graduated from beta to stable.
#
#   PIPELINE PATH → Deepgram STT + google.LLM + google.TTS
#     Activated when USE_GEMINI_REALTIME=false in .env.
#     Use this only if the Gemini Live WebSocket is unreliable in your region.
#
# COST BREAKDOWN (per 1-minute call, all-in):
#   VoiceLink SIP trunk      ≈ ₹1.00 / min   (fixed telephony cost)
#   Gemini 2.0 Flash Live   ≈ $0.000 / min   (free tier up to quota, then
#                                              $0.075 / 1M audio tokens ≈ ₹0.03/min)
#   LiveKit Cloud           ≈ $0.002 / min   ≈ ₹0.17 / min   (free tier exists)
#   Deepgram STT            ≈ $0.007 / min   ≈ ₹0.58 / min   (PIPELINE PATH ONLY)
#   Google TTS              ≈ $0.000 / min   ≈ ₹0.01 / min   (PIPELINE PATH ONLY)
#   ─────────────────────────────────────────────────────────────────────
#   REALTIME PATH TOTAL     ≈ ₹1.20 / min   ✅ under ₹1.50 target
#   PIPELINE PATH TOTAL     ≈ ₹1.78 / min   ⚠️  slightly over; use realtime
#
# =============================================================================

import json
import logging
import os
import ssl
import certifi
from typing import Optional

from dotenv import load_dotenv

# Patch ssl.create_default_context so aiohttp (used by LiveKit) picks up
# certifi's CA bundle. Must happen before any network library is imported.
_orig_create_default_context = ssl.create_default_context

def _certifi_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, **kwargs):
    if not kwargs.get("cafile") and not kwargs.get("capath") and not kwargs.get("cadata"):
        kwargs["cafile"] = certifi.where()
    return _orig_create_default_context(purpose, **kwargs)

ssl.create_default_context = _certifi_create_default_context

from livekit import agents, api, rtc
from livekit.agents import Agent, AgentSession, RoomInputOptions
try:
    from livekit.agents import RoomOptions as _RoomOptions
    _HAS_ROOM_OPTIONS = True
except ImportError:
    _HAS_ROOM_OPTIONS = False
from livekit.plugins import noise_cancellation, silero

from db import init_db, log_error, get_enabled_tools
from prompts import build_prompt
from tools import AppointmentTools


async def _log(level: str, msg: str, detail: str = "") -> None:
    """Write a structured log entry to Supabase and Python logger."""
    if level == "info":
        logger.info(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.error(msg)
    try:
        await log_error("agent", msg, detail, level)
    except Exception:
        pass

load_dotenv(".env")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbound-agent")

# Module-level constants are read after load_db_settings_to_env() runs in __main__,
# so DB-saved values win over .env values for these keys.
SIP_DOMAIN = os.getenv("VOICELINK_SIP_DOMAIN", "")


def load_db_settings_to_env() -> None:
    """
    Read every row from the Supabase settings table (synchronously) and push
    non-empty values into os.environ BEFORE the LiveKit worker starts.
    DB-saved API keys override .env values at startup.
    Called once in __main__ — not at import time.
    """
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        logger.warning("SUPABASE_URL or SUPABASE_SERVICE_KEY not set — skipping DB settings load")
        return
    try:
        from supabase import create_client
        client = create_client(url, key)
        result = client.table("settings").select("key, value").execute()
        for row in (result.data or []):
            if row.get("value"):
                os.environ[row["key"]] = row["value"]
                logger.debug("Loaded setting from Supabase: %s", row["key"])
    except Exception as exc:
        logger.warning("Could not load settings from Supabase: %s", exc)

# ---------------------------------------------------------------------------
# Try to import Google plugin paths in order of preference
# ---------------------------------------------------------------------------

_google_realtime = None      # google.realtime.RealtimeModel  (stable, >= 1.0)
_google_beta_realtime = None  # google.beta.realtime.RealtimeModel  (legacy)
_google_llm = None            # google.LLM  (pipeline fallback)
_google_tts = None            # google.TTS  (pipeline fallback)

try:
    from livekit.plugins import google as _gp
    try:
        _google_realtime = _gp.realtime.RealtimeModel
        logger.info("Loaded google.realtime.RealtimeModel (stable path)")
    except AttributeError:
        pass

    try:
        _google_beta_realtime = _gp.beta.realtime.RealtimeModel
        logger.info("Loaded google.beta.realtime.RealtimeModel (beta path)")
    except AttributeError:
        pass

    try:
        _google_llm = _gp.LLM
        _google_tts = _gp.TTS
    except AttributeError:
        pass

except ImportError:
    logger.warning("livekit-plugins-google not installed — cannot use Gemini")

# Deepgram as pipeline-mode STT fallback
_deepgram_stt = None
try:
    from livekit.plugins import deepgram as _dg
    _deepgram_stt = _dg.STT
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def _build_session(tools: list, system_prompt: str) -> AgentSession:
    """
    Build an AgentSession choosing the best available AI backend.
    Reads GEMINI_MODEL / GEMINI_TTS_VOICE / USE_GEMINI_REALTIME from os.environ
    at call time so DB-saved settings (loaded in __main__) take effect.
    Order of preference:
      1. google.realtime.RealtimeModel  (single-API Gemini Live audio)
      2. google.beta.realtime.RealtimeModel  (same, older package naming)
      3. Deepgram STT + google.LLM + google.TTS  (pipeline fallback)

    Silence-prevention config applied to all Live sessions:
      - session_resumption(transparent=True): auto-resumes after timeout instead of going silent
      - context_window_compression: compresses old turns with a sliding window instead of
        hitting the token limit and freezing
      - realtime_input_config: less aggressive end-of-speech VAD so Gemini doesn't end
        turns prematurely and stop listening
    """
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-live-001")
    gemini_voice = os.getenv("GEMINI_TTS_VOICE", "Aoede")
    use_realtime = os.getenv("USE_GEMINI_REALTIME", "true").lower() != "false"

    RealtimeClass = _google_realtime or (_google_beta_realtime if use_realtime else None)

    if use_realtime and RealtimeClass is not None:
        logger.info(
            "SESSION MODE: Gemini Live realtime (%s, voice=%s)", gemini_model, gemini_voice
        )
        # Build silence-prevention configs
        # NOTE: EndSensitivity uses full string values e.g. "END_SENSITIVITY_LOW", not .LOW
        try:
            from google.genai import types as _gt
            _realtime_input_cfg = _gt.RealtimeInputConfig(
                automatic_activity_detection=_gt.AutomaticActivityDetection(
                    end_of_speech_sensitivity=_gt.EndSensitivity.END_SENSITIVITY_LOW,
                    silence_duration_ms=2000,   # 2 s silence before ending turn
                    prefix_padding_ms=200,
                ),
            )
            _session_resumption_cfg = _gt.SessionResumptionConfig(transparent=True)
            _ctx_compression_cfg = _gt.ContextWindowCompressionConfig(
                trigger_tokens=25600,
                sliding_window=_gt.SlidingWindow(target_tokens=12800),
            )
            logger.info("Silence-prevention config applied (VAD LOW, transparent resumption, context compression)")
        except Exception as _cfg_err:
            logger.warning("Could not build silence-prevention config: %s", _cfg_err)
            _realtime_input_cfg = None
            _session_resumption_cfg = None
            _ctx_compression_cfg = None

        realtime_kwargs: dict = dict(
            model=gemini_model,
            voice=gemini_voice,
            instructions=system_prompt,
        )
        if _realtime_input_cfg is not None:
            realtime_kwargs["realtime_input_config"]      = _realtime_input_cfg
            realtime_kwargs["session_resumption"]         = _session_resumption_cfg
            realtime_kwargs["context_window_compression"] = _ctx_compression_cfg

        return AgentSession(
            llm=RealtimeClass(**realtime_kwargs),
            tools=tools,
        )

    # Pipeline fallback
    if _google_llm is None:
        raise RuntimeError(
            "No Google AI backend available. "
            "Run: pip install 'livekit-plugins-google>=1.0'"
        )

    logger.info("SESSION MODE: pipeline (Deepgram STT + Gemini LLM + Google TTS)")

    stt = _deepgram_stt(model="nova-3", language="multi") if _deepgram_stt else None
    tts = _google_tts() if _google_tts else None

    return AgentSession(
        stt=stt,
        llm=_google_llm(model="gemini-2.0-flash"),
        tts=tts,
        vad=silero.VAD.load(),
        tools=tools,
    )


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class OutboundAssistant(Agent):
    """Minimal Agent — all behaviour comes from the injected system prompt."""

    def __init__(self, instructions: str) -> None:
        super().__init__(instructions=instructions)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def entrypoint(ctx: agents.JobContext) -> None:
    """
    Main entrypoint called by the LiveKit worker for every dispatched job.

    Metadata fields read from ctx.job.metadata (JSON):
      phone_number   – E.164 number to dial (required for outbound)
      lead_name      – Name of the person being called
      business_name  – Name shown in the agent's persona
      service_type   – Service being offered
      system_prompt  – Full custom prompt (overrides default template if set)
    """
    await _log("info", f"Job started — room: {ctx.room.name}")

    # ------------------------------------------------------------------
    # Parse job metadata
    # ------------------------------------------------------------------
    phone_number: Optional[str] = None
    lead_name = "there"
    business_name = "our company"
    service_type = "our service"
    custom_prompt: Optional[str] = None

    voice_override: Optional[str] = None
    model_override: Optional[str] = None
    tools_override: Optional[str] = None

    if ctx.job.metadata:
        try:
            data = json.loads(ctx.job.metadata)
            phone_number   = data.get("phone_number")
            lead_name      = data.get("lead_name", lead_name)
            business_name  = data.get("business_name", business_name)
            service_type   = data.get("service_type", service_type)
            custom_prompt  = data.get("system_prompt")
            voice_override = data.get("voice_override")   # from agent profile
            model_override = data.get("model_override")   # from agent profile
            tools_override = data.get("tools_override")   # from agent profile (JSON string)
        except (json.JSONDecodeError, AttributeError):
            await _log("warning", "Invalid JSON in job metadata")

    await _log("info",
        f"Call job received — phone={phone_number} lead={lead_name} biz={business_name}",
        f"service={service_type} room={ctx.room.name}",
    )

    system_prompt = build_prompt(
        lead_name=lead_name,
        business_name=business_name,
        service_type=service_type,
        custom_prompt=custom_prompt,
    )

    tool_ctx = AppointmentTools(ctx, phone_number, lead_name)

    # Apply agent-profile overrides to environment for this session
    if voice_override:
        os.environ["GEMINI_TTS_VOICE"] = voice_override
    if model_override:
        os.environ["GEMINI_MODEL"] = model_override

    # Tools: profile override → global ENABLED_TOOLS setting → all
    if tools_override:
        import json as _j
        try:
            enabled_tools = _j.loads(tools_override)
        except Exception:
            enabled_tools = await get_enabled_tools()
    else:
        enabled_tools = await get_enabled_tools()  # [] = all tools enabled

    # ------------------------------------------------------------------
    # Connect to LiveKit room
    # ------------------------------------------------------------------
    await ctx.connect()
    await _log("info", f"Connected to LiveKit room: {ctx.room.name}")

    # ------------------------------------------------------------------
    # Outbound SIP dial — MUST happen before starting Gemini Live.
    # Gemini Live has a short idle timeout; if we start it before the
    # call is answered (~20-30s ring time) the session crashes silently
    # and generate_reply() raises "AgentSession isn't running".
    # ------------------------------------------------------------------
    # Determine if this is an outbound job (has phone_number in metadata)
    # or an inbound call (SIP participant already in the room, dispatched by LiveKit).
    # For inbound calls, phone_number will be None and we skip SIP dial.

    if phone_number:
        # ── OUTBOUND: Dial the lead ────────────────────────────────────────────────
        trunk_id = os.getenv("OUTBOUND_TRUNK_ID")
        if not trunk_id:
            await _log("error", "OUTBOUND_TRUNK_ID not set — cannot place outbound call")
            ctx.shutdown()
            return

        await _log("info", f"[OUTBOUND] Dialing {phone_number} via SIP trunk {trunk_id}")
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=trunk_id,
                    sip_call_to=phone_number,
                    participant_identity=f"sip_{phone_number}",
                    wait_until_answered=True,
                )
            )
        except Exception as exc:
            await _log("error", f"SIP dial FAILED for {phone_number}: {exc}",
                       f"trunk_id={trunk_id} room={ctx.room.name}")
            ctx.shutdown()
            return
        await _log("info", f"[OUTBOUND] Call ANSWERED — {phone_number} picked up")
    else:
        # ── INBOUND: Caller rang one of our VoiceLink DIDs ────────────────────────
        await _log("info", f"[INBOUND] Inbound call received in room: {ctx.room.name}")
        import asyncio as _asyncio
        await _asyncio.sleep(1)
        for participant in ctx.room.remote_participants.values():
            attrs = getattr(participant, "attributes", {}) or {}
            sip_call_from = attrs.get("sip.callFrom") or attrs.get("sip.phoneNumber") or ""
            if sip_call_from:
                phone_number = sip_call_from
                await _log("info", f"[INBOUND] Caller identified as: {phone_number}")
                break

    # ------------------------------------------------------------------
    # Build and start Gemini Live session AFTER the call is answered
    # ------------------------------------------------------------------
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-live-001")
    await _log("info", f"Building AI session — model={gemini_model}")
    active_tools = tool_ctx.build_tool_list(enabled_tools)
    await _log("info", f"Tools loaded: {[t.__name__ for t in active_tools]}")
    session = _build_session(tools=active_tools, system_prompt=system_prompt)

    # Noise cancellation: OFF by default for SIP/VoiceLink calls.
    # VoiceLink PSTN already processes audio; BVCTelephony on top filters
    # the lead's voice as "noise" → Gemini hears silence → call goes quiet.
    # Set ENABLE_NOISE_CANCELLATION=true only for raw mic/browser testing.
    _enable_nc = os.getenv("ENABLE_NOISE_CANCELLATION", "false").lower() == "true"
    _input_opts = RoomInputOptions(
        noise_cancellation=noise_cancellation.BVCTelephony() if _enable_nc else None,
    )
    await _log("info", f"Noise cancellation: {'ON (BVCTelephony)' if _enable_nc else 'OFF'}")

    # Build session start kwargs using RoomOptions if available (non-deprecated),
    # otherwise fall back to the old RoomInputOptions.
    # IMPORTANT: do NOT use close_on_disconnect=True — SIP legs frequently have
    # brief audio dropouts that look like disconnects. We handle shutdown ourselves
    # by watching for the SIP participant actually leaving the room.
    if _HAS_ROOM_OPTIONS:
        from livekit.agents import RoomOptions as _RO
        _session_kwargs = dict(
            room=ctx.room,
            agent=OutboundAssistant(instructions=system_prompt),
            room_options=_RO(
                input_options=_input_opts,
            ),
        )
    else:
        _session_kwargs = dict(
            room=ctx.room,
            agent=OutboundAssistant(instructions=system_prompt),
            room_input_options=_input_opts,
        )

    await session.start(**_session_kwargs)
    await _log("info", "Agent session started — AI ready, generating greeting")

    # ------------------------------------------------------------------
    # Optional egress recording (only if S3 configured)
    # ------------------------------------------------------------------
    if phone_number:
        # Support both S3_ prefix (Supabase Storage convention) and AWS_ prefix
        _aws_key    = os.getenv("S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID", "")
        _aws_secret = os.getenv("S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY", "")
        _aws_bucket = os.getenv("S3_BUCKET") or os.getenv("AWS_BUCKET_NAME", "")
        _s3_endpoint = os.getenv("S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT", "")
        _s3_region  = os.getenv("S3_REGION") or os.getenv("AWS_REGION", "ap-northeast-1")
        if _aws_key and _aws_secret and _aws_bucket:
            try:
                _recording_path = f"recordings/{ctx.room.name}.ogg"
                _egress_req = api.RoomCompositeEgressRequest(
                    room_name=ctx.room.name,
                    audio_only=True,
                    file_outputs=[
                        api.EncodedFileOutput(
                            file_type=api.EncodedFileType.OGG,
                            filepath=_recording_path,
                            s3=api.S3Upload(
                                access_key=_aws_key,
                                secret=_aws_secret,
                                bucket=_aws_bucket,
                                region=_s3_region,
                                endpoint=_s3_endpoint,
                            ),
                        )
                    ],
                )
                _egress = await ctx.api.egress.start_room_composite_egress(_egress_req)
                _s3_ep = _s3_endpoint.rstrip("/")
                tool_ctx.recording_url = (
                    f"{_s3_ep}/{_aws_bucket}/{_recording_path}"
                    if _s3_ep
                    else f"s3://{_aws_bucket}/{_recording_path}"
                )
                await _log("info", f"Recording started: egress={_egress.egress_id}")
            except Exception as _exc:
                await _log("warning", f"Recording start failed (non-fatal): {_exc}")

    # ------------------------------------------------------------------
    # Greet — trigger the model to speak first.
    # NOTE: gemini-3.1-flash-live-preview does NOT support generate_reply()
    # — the plugin explicitly blocks it. The 3.1 model speaks autonomously
    # from the system prompt as soon as the audio session is established.
    # For other models, generate_reply() triggers the opening line.
    # ------------------------------------------------------------------
    is_outbound = bool(ctx.job.metadata and
                       json.loads(ctx.job.metadata or "{}").get("phone_number"))
    greeting_instructions = (
        f"The call just connected. This is an OUTBOUND call. "
        f"Greet the lead and ask if you're speaking with {lead_name}, "
        f"as per your instructions."
        if is_outbound
        else "The call just connected. This is an INBOUND call from a customer who dialled "
             "your number. Greet them warmly, introduce yourself, and ask how you can help."
    )
    try:
        await session.generate_reply(instructions=greeting_instructions)
        await _log("info", "Greeting triggered via generate_reply")
    except Exception as _gr_exc:
        await _log("warning", f"generate_reply failed (native-audio model expected): {_gr_exc}. Relying on autonomous greet.")

    # ------------------------------------------------------------------
    # Keep session alive until the SIP participant actually leaves.
    # This is critical — without this block, the entrypoint can return
    # before the call ends, causing the process to spin down prematurely.
    # We watch the room for the SIP participant disconnecting, then give
    # a short grace period (re-connection window) before shutting down.
    # ------------------------------------------------------------------
    import asyncio
    import time

    if phone_number:
        _sip_identity = f"sip_{phone_number}"
        _disconnect_event = asyncio.Event()

        def _on_participant_disconnected(participant: rtc.RemoteParticipant):
            if participant.identity == _sip_identity:
                _disconnect_event.set()

        ctx.room.on("participant_disconnected", _on_participant_disconnected)

        # Also watch for the room itself closing (e.g. LiveKit server timeout)
        def _on_disconnected():
            _disconnect_event.set()
        ctx.room.on("disconnected", _on_disconnected)

        # ── Inactivity observability watchdog ──────────────────────────────
        # Passive monitor: tracks the last time either side spoke and emits
        # WARNING-level logs when silence exceeds 20 s and 40 s thresholds.
        # We deliberately do NOT call session.generate_reply() here — it is
        # explicitly blocked by livekit-plugins-google for 3.1 / 2.5 native-
        # audio models (see plugin warning: "limited mid-session update
        # support"), so any nudge would silently no-op while papering over
        # the real problem in production.
        # Instead, we surface the silence as a structured warning so it shows
        # up in /api/logs and you can correlate with carrier / network events.
        _last_speech = [time.time()]
        _warned_thresholds: set = set()

        def _on_any_speech(*_args):
            _last_speech[0] = time.time()
            _warned_thresholds.clear()

        for _ev in ("agent_started_speaking", "user_started_speaking",
                    "agent_speech_committed", "user_speech_committed"):
            try:
                session.on(_ev, _on_any_speech)
            except Exception:
                pass  # event names differ by plugin version — not fatal

        async def _silence_watchdog():
            # Grace period — let the greeting + initial response finish first
            await asyncio.sleep(20)
            while not _disconnect_event.is_set():
                try:
                    await asyncio.wait_for(_disconnect_event.wait(), timeout=5)
                    break
                except asyncio.TimeoutError:
                    pass
                silence_sec = time.time() - _last_speech[0]
                # Two-tier alerting so a single call doesn't spam logs
                for threshold in (20, 40):
                    if silence_sec >= threshold and threshold not in _warned_thresholds:
                        _warned_thresholds.add(threshold)
                        await _log(
                            "warning",
                            f"Silence watchdog: {silence_sec:.0f}s without speech",
                            f"phone={phone_number} room={ctx.room.name} model={os.getenv('GEMINI_MODEL', '')}",
                        )

        _watchdog_task = asyncio.create_task(_silence_watchdog())

        # Wait until the SIP leg genuinely drops
        try:
            await asyncio.wait_for(_disconnect_event.wait(), timeout=3600)  # max 1h
        except asyncio.TimeoutError:
            await _log("warning", "Call reached 1-hour safety timeout — shutting down")
        finally:
            _watchdog_task.cancel()
            try:
                await _watchdog_task
            except asyncio.CancelledError:
                pass

        await _log("info", f"SIP participant disconnected — ending session for {phone_number}")
        await session.aclose()
    else:
        # Inbound / test call — just wait for the session to finish naturally
        import asyncio
        _done = asyncio.Event()

        def _on_room_disconnected():
            _done.set()
        ctx.room.on("disconnected", _on_room_disconnected)

        try:
            await asyncio.wait_for(_done.wait(), timeout=3600)
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Worker entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()                    # create tables if they don't exist
    load_db_settings_to_env()    # push DB-saved API keys into os.environ before worker starts
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller-shreyas",
        )
    )
