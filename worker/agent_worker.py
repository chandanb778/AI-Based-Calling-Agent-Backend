"""
LiveKit agent worker entrypoint.

This is the function that LiveKit calls for each dispatched job.
It orchestrates the full call lifecycle:

1. Connect to the LiveKit room
2. Parse dispatch metadata (phone number, contact name)
3. Create the agent and voice pipeline
4. Start session → Dial via SIP → Proactive greeting
5. Monitor call duration (cost protection)
6. Wait for disconnect → Log to Supabase
"""

from __future__ import annotations

import asyncio
import json
import time

from livekit import rtc, api
from livekit.agents import JobContext

from app.config import settings
from app.db.call_logs import insert_call_log
from app.db.leads import insert_lead
from app.services.agent_service import (
    RealEstateAgent,
    create_agent_session,
    wire_transcript_events,
    enforce_max_duration,
    get_greeting_instructions,
    DEFAULT_LANGUAGE,
)
from app.services.lead_service import extract_lead_from_transcript
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def entrypoint(ctx: JobContext) -> None:
    """
    Main entry point for each outbound call.

    Called by the LiveKit agent framework when a job is dispatched
    (either from /make-call or /bulk-call).
    """
    logger.info("🏠 Connecting to room: %s", ctx.room.name)
    await ctx.connect()

    # ── Parse dispatch metadata ──
    try:
        dial_info = json.loads(ctx.job.metadata) if ctx.job.metadata else {}
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON in job metadata")
        ctx.shutdown()
        return

    phone_number = dial_info.get("phone_number", "")
    contact_name = dial_info.get("contact_name", "the customer")
    language = dial_info.get("language", DEFAULT_LANGUAGE)

    if not phone_number:
        logger.error("❌ No phone_number in dispatch metadata")
        ctx.shutdown()
        return

    if not settings.sip_outbound_trunk_id:
        logger.error("❌ SIP_OUTBOUND_TRUNK_ID not configured")
        ctx.shutdown()
        return

    participant_identity = phone_number
    logger.info(
        "📱 Preparing to call: %s (contact: %s, language: %s)",
        phone_number, contact_name, language,
    )

    # ── Create agent + session (language-aware) ──
    agent = RealEstateAgent(phone_number=phone_number, language=language)
    agent.call_start_time = time.time()

    session = create_agent_session(language=language)
    wire_transcript_events(session, agent)

    # ── Start session BEFORE dialing (don't miss first words) ──
    session_started = asyncio.create_task(
        session.start(agent=agent, room=ctx.room)
    )

    # ── Dial via SIP ──
    try:
        logger.info("📞 Dialing %s...", phone_number)
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=settings.sip_outbound_trunk_id,
                sip_call_to=phone_number,
                participant_identity=participant_identity,
                wait_until_answered=True,
            )
        )

        await session_started
        participant = await ctx.wait_for_participant(identity=participant_identity)
        logger.info("✅ Call connected: %s", participant.identity)

        agent.set_participant(participant)
        agent.call_start_time = time.time()

        # ── Proactive greeting — language-aware ──
        greeting = get_greeting_instructions(language, contact_name)
        await session.generate_reply(instructions=greeting)

    except api.TwirpError as e:
        logger.error(
            "❌ SIP call failed: %s, SIP status: %s %s",
            e.message,
            e.metadata.get("sip_status_code"),
            e.metadata.get("sip_status"),
        )
        ctx.shutdown()
        return
    except Exception as e:
        logger.error("❌ Unexpected error placing call: %s", e)
        ctx.shutdown()
        return

    # ── Cost protection: max duration enforcer ──
    duration_task = asyncio.create_task(
        enforce_max_duration(session, agent)
    )

    # ── Wait for disconnect ──
    disconnect_event = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def on_participant_left(p: rtc.RemoteParticipant):
        if p.identity == participant_identity:
            logger.info("📴 Caller disconnected: %s", p.identity)
            disconnect_event.set()

    @ctx.room.on("disconnected")
    def on_room_disconnected():
        logger.info("📴 Room disconnected")
        disconnect_event.set()

    await disconnect_event.wait()

    # ── Cleanup ──
    duration_task.cancel()
    call_duration = time.time() - agent.call_start_time

    full_transcript = (
        "\n".join(agent.transcript_lines)
        if agent.transcript_lines
        else "(no transcript captured)"
    )

    logger.info(
        "📊 Call summary: %s, duration=%ds, transcript_lines=%d",
        phone_number,
        round(call_duration),
        len(agent.transcript_lines),
    )

    # ── Log to Supabase (error-isolated) ──
    await insert_call_log(
        caller_number=phone_number,
        duration_seconds=call_duration,
        transcript=full_transcript,
    )

    # ── Extract lead from transcript (error-isolated) ──
    logger.info("🎯 Extracting lead data from transcript for %s...", phone_number)
    lead_data = await extract_lead_from_transcript(
        transcript=full_transcript,
        phone_number=phone_number,
        contact_name=contact_name,
    )

    if lead_data:
        await insert_lead(lead_data)
    else:
        logger.warning("⚠️  No lead data extracted for %s", phone_number)
