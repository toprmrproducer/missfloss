import asyncio
import logging
import os
import time
from typing import Optional

from livekit import agents, api
from livekit.agents import llm

from db import (
    check_slot, get_next_available, insert_appointment, log_call, log_error,
    get_calls_by_phone, get_appointments_by_phone,
    add_contact_memory, get_contact_memory, compress_contact_memory,
)

logger = logging.getLogger("appointment-tools")

async def _log(msg: str, detail: str = "", level: str = "info") -> None:
    try:
        await log_error("agent", msg, detail, level)
    except Exception:
        pass


class AppointmentTools(llm.ToolContext):
    """All function tools available to the appointment-booking agent."""

    def __init__(
        self,
        ctx: agents.JobContext,
        phone_number: Optional[str] = None,
        lead_name: Optional[str] = None,
    ):
        # Set instance attrs before calling super so bound methods are ready
        self.ctx = ctx
        self.phone_number = phone_number
        self.lead_name = lead_name
        self._call_start_time = time.time()
        self._sip_domain = os.getenv("VOBIZ_SIP_DOMAIN", "")
        self.recording_url: Optional[str] = None
        super().__init__(tools=[])

    # Tool registry — name → method
    _TOOL_REGISTRY = {
        "check_availability":    "check_availability",
        "book_appointment":      "book_appointment",
        "end_call":              "end_call",
        "transfer_to_human":     "transfer_to_human",
        "send_sms_confirmation": "send_sms_confirmation",
        "lookup_contact":        "lookup_contact",
        "remember_details":      "remember_details",
        "book_calcom":           "book_calcom",
        "cancel_calcom":         "cancel_calcom",
    }

    def build_tool_list(self, enabled: list) -> list:
        """Return tool methods filtered by the enabled list. Empty list = all enabled."""
        all_methods = [
            self.check_availability,
            self.book_appointment,
            self.end_call,
            self.transfer_to_human,
            self.send_sms_confirmation,
            self.lookup_contact,
            self.remember_details,
            self.book_calcom,
            self.cancel_calcom,
        ]
        if not enabled:
            return all_methods
        name_map = {m.__name__: m for m in all_methods}
        return [name_map[n] for n in enabled if n in name_map]

    @property
    def all_tools(self) -> list:
        return [
            self.check_availability,
            self.book_appointment,
            self.end_call,
            self.transfer_to_human,
            self.send_sms_confirmation,
            self.lookup_contact,
            self.remember_details,
            self.book_calcom,
            self.cancel_calcom,
        ]

    # ------------------------------------------------------------------ #
    #  Tool 1: check_availability                                          #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def check_availability(self, date: str, time: str) -> str:
        """
        Check whether a date/time slot is available for booking.
        Call this BEFORE attempting to book whenever the lead proposes a date/time.
        date format: YYYY-MM-DD  |  time format: HH:MM (24-hour clock)
        Returns 'available' or 'unavailable: next available slot is <slot>'.
        """
        try:
            if await check_slot(date, time):
                await _log(f"Tool: check_availability({date} {time}) → available")
                return "available"
            next_slot = await get_next_available(date, time)
            await _log(f"Tool: check_availability({date} {time}) → unavailable, next: {next_slot}")
            return f"unavailable: next available slot is {next_slot}"
        except Exception as exc:
            logger.error("check_availability error: %s", exc)
            return "Unable to check availability right now — please suggest a date and I will confirm."

    # ------------------------------------------------------------------ #
    #  Tool 2: book_appointment                                            #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def book_appointment(
        self, name: str, phone: str, date: str, time: str, service: str
    ) -> str:
        """
        Book an appointment after the lead has verbally confirmed date, time, and service.
        Call ONLY after the lead confirms all details.
        name: lead's full name
        phone: lead's phone number with country code
        date: YYYY-MM-DD
        time: HH:MM (24-hour clock)
        service: service type requested
        Returns a confirmation message with a short booking ID.
        """
        try:
            await _log(f"Tool: book_appointment — {name} {phone} {date} {time} {service}")
            booking_id = await insert_appointment(name, phone, date, time, service)
            await _log(f"Tool: booking CONFIRMED — ID={booking_id} for {name}")
            return (
                f"Confirmed! Your booking ID is {booking_id}. "
                f"We'll see you on {date} at {time} for your {service}."
            )
        except Exception as exc:
            logger.error("book_appointment error: %s", exc)
            return (
                "I had a technical issue saving the booking. "
                "Our team will call you back to confirm shortly."
            )

    # ------------------------------------------------------------------ #
    #  Tool 3: end_call                                                    #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def end_call(self, outcome: str, reason: str = "") -> str:
        """
        End the call gracefully after logging the outcome.
        Call when:
        - Appointment booked successfully        → outcome='booked'
        - Lead is not interested                 → outcome='not_interested'
        - Wrong number reached                   → outcome='wrong_number'
        - Lead asked to call back later          → outcome='callback_requested'
        - Voicemail detected                     → outcome='voicemail'
        outcome: one of the values above
        reason: brief free-text description of why the call ended
        """
        await _log(f"Tool: end_call — outcome={outcome} reason={reason}", level="info")
        duration = int(time.time() - self._call_start_time)
        try:
            await log_call(
                phone_number=self.phone_number or "unknown",
                lead_name=self.lead_name,
                outcome=outcome,
                reason=reason,
                duration_seconds=duration,
                recording_url=self.recording_url,
            )
        except Exception as exc:
            logger.error("Failed to log call outcome: %s", exc)

        try:
            await self.ctx.room.disconnect()
        except Exception as exc:
            logger.warning("Room disconnect error: %s", exc)

        return "Call ended."

    # ------------------------------------------------------------------ #
    #  Tool 4: transfer_to_human                                           #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def transfer_to_human(self, reason: str) -> str:
        """
        Transfer the call to a human agent using SIP REFER.
        Call when:
        - Lead explicitly asks to speak to a human
        - Lead raises a complex objection the AI cannot resolve
        - Lead is angry or upset
        reason: brief description of why the transfer is happening
        """
        destination = os.getenv("DEFAULT_TRANSFER_NUMBER", "")
        if not destination:
            return "Transfer unavailable: no fallback number is configured."

        # Build a valid SIP URI from the raw phone number
        if "@" not in destination:
            clean = destination.replace("tel:", "").replace("sip:", "")
            if self._sip_domain:
                destination = f"sip:{clean}@{self._sip_domain}"
            else:
                destination = f"tel:{clean}"
        elif not destination.startswith("sip:"):
            destination = f"sip:{destination}"

        # Identify the SIP participant to transfer
        participant_identity = None
        if self.phone_number:
            participant_identity = f"sip_{self.phone_number}"
        else:
            for p in self.ctx.room.remote_participants.values():
                participant_identity = p.identity
                break

        if not participant_identity:
            return "Transfer failed: could not identify the caller's participant."

        try:
            await self.ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=self.ctx.room.name,
                    participant_identity=participant_identity,
                    transfer_to=destination,
                    play_dialtone=False,
                )
            )
            logger.info("Transfer initiated → %s (reason: %s)", destination, reason)
            await _log(f"Tool: transfer_to_human → {destination} | reason: {reason}")
            return "Transferring you to a human agent now. Please hold for a moment."
        except Exception as exc:
            logger.error("Transfer failed: %s", exc)
            return "I wasn't able to complete the transfer. Please call us back directly."

    # ------------------------------------------------------------------ #
    #  Tool 5: send_sms_confirmation (optional — skips if Twilio absent)  #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def send_sms_confirmation(self, phone: str, message: str) -> str:
        """
        Send an SMS confirmation to the lead after a successful booking.
        Call ONLY after book_appointment succeeds.
        Skips silently if Twilio credentials are not configured.
        phone: lead's phone number with country code
        message: the confirmation text to send
        """
        sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        token = os.getenv("TWILIO_AUTH_TOKEN", "")
        from_num = os.getenv("TWILIO_FROM_NUMBER", "")

        if not (sid and token and from_num):
            return "SMS skipped: Twilio not configured."

        try:
            from twilio.rest import Client  # lazy import — only needed if Twilio is configured

            loop = asyncio.get_event_loop()
            client = Client(sid, token)
            # Twilio client is synchronous; run in thread pool to avoid blocking
            await loop.run_in_executor(
                None,
                lambda: client.messages.create(body=message, from_=from_num, to=phone),
            )
            logger.info("SMS confirmation sent to %s", phone)
            await _log(f"Tool: send_sms_confirmation → {phone}")
            return f"SMS confirmation sent to {phone}."
        except Exception as exc:
            logger.error("SMS send failed: %s", exc)
            return "SMS delivery failed, but your booking is confirmed in our system."

    # ------------------------------------------------------------------ #
    #  Tool 6: lookup_contact                                              #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def lookup_contact(self, phone: str) -> str:
        """
        Look up a contact's full history from the database before engaging in conversation.
        Call this at the start of a call (or any time) to understand the lead's background:
        previous call outcomes, existing appointments, and any notes left by the team.
        phone: the lead's phone number with country code
        Returns a structured summary of the contact's history.
        """
        try:
            calls = await get_calls_by_phone(phone)
            appointments = await get_appointments_by_phone(phone)
            await _log(f"Tool: lookup_contact({phone}) — {len(calls)} calls, {len(appointments)} appointments")

            if not calls and not appointments:
                return f"No history found for {phone}. This appears to be a first-time contact."

            lines = [f"Contact history for {phone}:"]

            # Remembered details (highest priority — show first)
            memories = await get_contact_memory(phone)
            if memories:
                lines.append(f"\nREMEMBERED DETAILS ({len(memories)} entries):")
                for m in memories[:10]:
                    lines.append(f"  • {m['insight']}")

            if calls:
                lines.append(f"\nCALL HISTORY ({len(calls)} calls):")
                for c in calls[:5]:
                    ts = (c.get("timestamp") or "")[:16]
                    outcome = c.get("outcome", "unknown")
                    reason = c.get("reason", "")
                    notes = c.get("notes", "")
                    line = f"  • {ts} — outcome: {outcome}"
                    if reason:
                        line += f", reason: {reason}"
                    if notes:
                        line += f", notes: {notes}"
                    lines.append(line)
                if len(calls) > 5:
                    lines.append(f"  … and {len(calls)-5} more calls")

            if appointments:
                lines.append(f"\nAPPOINTMENTS ({len(appointments)}):")
                for a in appointments[:3]:
                    status = a.get("status", "unknown")
                    lines.append(f"  • {a.get('date')} {a.get('time')} — {a.get('service')} [{status}]")

            return "\n".join(lines)
        except Exception as exc:
            logger.error("lookup_contact error: %s", exc)
            return "Unable to retrieve contact history right now."

    # ------------------------------------------------------------------ #
    #  Tool 7: remember_details                                            #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def remember_details(self, insight: str) -> str:
        """
        Store a key insight or detail about this person for future calls.
        Call this whenever you learn something useful about the lead:
        their preferences, objections, family situation, interest level,
        best time to call, or any other detail that will help future conversations.
        Examples:
          "Prefers morning calls, before 10am"
          "Has 2 kids, interested in family dental plan"
          "Said she will discuss with husband and wants callback in 2 weeks"
          "Very interested in the premium package, budget is ₹5000/month"
        insight: the key detail to remember (plain text)
        Returns confirmation.
        """
        if not self.phone_number:
            return "Cannot remember detail — no phone number for this call."
        try:
            await add_contact_memory(self.phone_number, insight)
            await _log(f"Tool: remember_details({self.phone_number}) — {insight[:60]}")

            # After saving, check if we have many entries and compress them
            memories = await get_contact_memory(self.phone_number)
            if len(memories) >= 5:
                asyncio.create_task(self._compress_memories())

            return f"Remembered: {insight}"
        except Exception as exc:
            logger.error("remember_details error: %s", exc)
            return "Could not save the detail right now."

    async def _compress_memories(self) -> None:
        """Use Gemini Flash to compress multiple memory entries into a concise profile."""
        try:
            memories = await get_contact_memory(self.phone_number)
            if len(memories) < 5:
                return
            import google.generativeai as genai
            api_key = os.getenv("GOOGLE_API_KEY", "")
            if not api_key:
                return
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            bullet_list = "\n".join(f"- {m['insight']}" for m in memories)
            prompt = (
                f"Compress these notes about a sales contact into a concise 3-5 bullet profile. "
                f"Keep all key facts. Be terse.\n\n{bullet_list}"
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: model.generate_content(prompt))
            compressed = response.text.strip()
            if compressed:
                await compress_contact_memory(self.phone_number, compressed)
                logger.info("Compressed memories for %s", self.phone_number)
        except Exception as exc:
            logger.warning("Memory compression failed: %s", exc)

    # ------------------------------------------------------------------ #
    #  Tool 8: book_calcom                                                 #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def book_calcom(
        self,
        name: str,
        email: str,
        date: str,
        start_time: str,
        notes: str = "",
    ) -> str:
        """
        Book an appointment in Cal.com calendar.
        Call AFTER book_appointment succeeds to sync with the team's Cal.com calendar.
        name: lead's full name
        email: lead's email address (required by Cal.com)
        date: YYYY-MM-DD
        start_time: HH:MM (24-hour)
        notes: any special notes for the appointment
        Returns the Cal.com booking UID or an error.
        """
        api_key = os.getenv("CALCOM_API_KEY", "")
        event_type_id = os.getenv("CALCOM_EVENT_TYPE_ID", "")
        timezone = os.getenv("CALCOM_TIMEZONE", "Asia/Kolkata")
        if not api_key or not event_type_id:
            return "Cal.com not configured — skipping calendar booking. Add CALCOM_API_KEY and CALCOM_EVENT_TYPE_ID in Settings."

        try:
            from datetime import datetime as _dt
            start_dt = _dt.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
            start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.cal.com/v1/bookings",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "eventTypeId": int(event_type_id),
                        "start": start_iso,
                        "timeZone": timezone,
                        "responses": {"name": name, "email": email, "notes": notes},
                        "metadata": {"source": "OutboundAI"},
                        "language": "en",
                    },
                )
            data = resp.json()
            if resp.status_code not in (200, 201):
                raise ValueError(data.get("message") or str(data))

            uid = data.get("uid", "")
            await _log(f"Tool: book_calcom → uid={uid} for {name}")
            return f"Cal.com appointment booked. Booking UID: {uid}"
        except Exception as exc:
            logger.error("book_calcom error: %s", exc)
            return f"Cal.com booking failed: {exc}"

    # ------------------------------------------------------------------ #
    #  Tool 9: cancel_calcom                                               #
    # ------------------------------------------------------------------ #

    @llm.function_tool
    async def cancel_calcom(self, booking_uid: str, reason: str = "") -> str:
        """
        Cancel a Cal.com appointment by its booking UID.
        Use the UID returned by book_calcom.
        booking_uid: the Cal.com booking UID to cancel
        reason: optional cancellation reason
        Returns confirmation or an error.
        """
        api_key = os.getenv("CALCOM_API_KEY", "")
        if not api_key:
            return "Cal.com not configured — cannot cancel."

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.delete(
                    f"https://api.cal.com/v1/bookings/{booking_uid}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"reason": reason} if reason else {},
                )
            if resp.status_code not in (200, 204):
                raise ValueError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            await _log(f"Tool: cancel_calcom → cancelled uid={booking_uid}")
            return f"Cal.com appointment {booking_uid} cancelled successfully."
        except Exception as exc:
            logger.error("cancel_calcom error: %s", exc)
            return f"Cal.com cancellation failed: {exc}"
