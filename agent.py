"""
Real Estate AI Outbound Voice Agent
A self-hosted outbound voice agent using LiveKit Agents framework.
Pipeline: Sarvam STT→Groq LLM→Sarvam TTS
VAD:Silero (tunable parameters below)
Calls:Twilio via LiveKit SIP trunking
Logging:Airtable (call_logs table)
Trigger:FastAPI HTTP endpoint + lk CLI dispatch
Author:Horizon Realty Engineering
"""

from __future__ import annotations

import asyncio
import logging
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from livekit import rtc, api
from livekit.agents import (
    AgentSession,
    Agent,
    JobContext,
    function_tool,
    RunContext,
    get_job_context,
    cli,
    WorkerOptions,
    RoomInputOptions,
)
from livekit.plugins import silero, sarvam, groq

# ─── FastAPI for HTTP call triggering ───
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import threading

# ─── Airtable for call logging ───
from pyairtable import Api as AirtableApi

# ────────────────────────────────────────────────────────────────────
# 1. ENVIRONMENT CONFIGURATION
# ────────────────────────────────────────────────────────────────────
# Load environment variables from .env file (never hardcode secrets!)
load_dotenv(dotenv_path=".env.local")

# Set up logging so we can trace what's happening during calls
logger = logging.getLogger("real-estate-agent")
logger.setLevel(logging.INFO)

# ── LiveKit Cloud connection ──
LIVEKIT_URL = os.getenv("LIVEKIT_URL")                  # Your LiveKit Cloud WebSocket URL
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")           # API key from LiveKit dashboard
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")     # API secret from LiveKit dashboard

# ── SIP / Twilio outbound trunk ──
OUTBOUND_TRUNK_ID = os.getenv("SIP_OUTBOUND_TRUNK_ID")  # Trunk ID for outbound calls via Twilio

# ── Airtable logging ──
AIRTABLE_PAT = os.getenv("AIRTABLE_PAT")                # Airtable Personal Access Token
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")        # Airtable Base ID
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "call_logs")  # Table name (defaults to call_logs)

# ── Cost protection ──
# Maximum call duration in seconds — prevents runaway costs from stuck calls
MAX_CALL_DURATION = int(os.getenv("MAX_CALL_DURATION_SECONDS", "600"))  # Default: 10 minutes

# ── FastAPI server port for HTTP call triggering ──
API_PORT = int(os.getenv("API_PORT", "8081"))

# ────────────────────────────────────────────────────────────────────
# 2. SYSTEM PROMPT — Real Estate Buyer Qualification Agent
# ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are Anand, a professional real estate agent from Horizon Realty.
Your goal is to qualify property buyers through a natural, human-like phone conversation and classify them as HOT, WARM, or COLD leads.
This is a VOICE conversation:
- Keep responses VERY SHORT (under 12 words unless needed)
- Speak naturally like a real person
- Ask only ONE question at a time
- Acknowledge before asking next
=========================
FLOW

1. GREETING
- Confirm identity
- Mention their property interest
- Ask if they can talk now
- If busy → schedule callback
2. INTEREST
- Are they actively looking?
- If not → politely end
- If browsing → continue gently
3. QUALIFICATION (BANT)
BUDGET → Ask range (suggest if hesitant)  
AUTHORITY → Decision maker? Anyone else involved?  
NEED → Property type + location + loan requirement  
TIMELINE → When planning to buy?
4. BEHAVIOR
- Adapt to user tone (excited, confused, hesitant)
- Be polite, confident, and human
- Never sound robotic

===========================
RULES
- Keep responses short and conversational
- Do NOT ask multiple questions together
- Do NOT repeat yourself
- Gently steer back if off-topic
- If unsure → say a specialist will follow up
- NEVER hallucinate property details
- End call using end_call tool when done
""".strip()


# ────────────────────────────────────────────────────────────────────
# 3. AIRTABLE LOGGING (error-isolated)
# ────────────────────────────────────────────────────────────────────

def log_call_to_airtable(
    caller_number: str,
    duration_seconds: float,
    transcript: str,
) -> None:
    """
    Log call details to Airtable after the call ends.

    This runs in a try/except block so that if Airtable is down or
    misconfigured, the call itself does NOT crash. We just log the
    error and move on.
    """
    try:
        # Validate that Airtable credentials are set
        if not all([AIRTABLE_PAT, AIRTABLE_BASE_ID]):
            logger.warning("⚠️ Airtable credentials not configured — skipping call log")
            return

        logger.info(f"📝 Attempting Airtable log — PAT: {AIRTABLE_PAT[:10]}..., Base: {AIRTABLE_BASE_ID}, Table: {AIRTABLE_TABLE_NAME}")

        # Use the new Api.table() method (Table() constructor is deprecated)
        airtable_api = AirtableApi(AIRTABLE_PAT)
        table = airtable_api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

        # Build the record payload.
        # IMPORTANT: Field names must EXACTLY match your Airtable column names.
        # Check your Airtable base and update these keys to match.
        record = {
            "caller_number": caller_number,
            "duration_seconds": round(duration_seconds, 1),
            "transcript": transcript,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }

        logger.info(f"📝 Airtable record payload: {list(record.keys())}")

        # Insert a new record with the call details
        result = table.create(record)
        logger.info(f"✅ Call logged to Airtable — {caller_number}, {round(duration_seconds)}s, record_id={result.get('id', 'unknown')}")

    except Exception as e:
        # IMPORTANT: We catch ALL exceptions here so logging failures
        # never bring down the voice agent or crash an active call
        logger.error(f"❌ Failed to log call to Airtable: {e}")
        logger.error("💡 FIX: Go to https://airtable.com/create/tokens → edit your PAT → "
                      "add scopes 'data.records:read' + 'data.records:write' → "
                      "grant access to your specific base")


# ────────────────────────────────────────────────────────────────────
# 4. REAL ESTATE AGENT CLASS
# ────────────────────────────────────────────────────────────────────

class RealEstateAgent(Agent):
    """
    The AI voice agent that handles the conversation with the caller.
    Inherits from LiveKit's Agent class and uses function tools for
    call control actions.
    """

    def __init__(self, *, phone_number: str):
        super().__init__(instructions=SYSTEM_PROMPT)

        # Track the remote participant (the person on the phone)
        self.participant: rtc.RemoteParticipant | None = None
        self.phone_number = phone_number

        # Transcript accumulator — we build this during the call
        self.transcript_lines: list[str] = []
        self.call_start_time: float = 0.0

    def set_participant(self, participant: rtc.RemoteParticipant):
        """Store reference to the phone participant once they join the room."""
        self.participant = participant

    async def hangup(self):
        """
        Hang up the call by deleting the LiveKit room.
        This disconnects all participants and ends the SIP session.
        """
        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(room=job_ctx.room.name)
        )

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """Called when the conversation is complete or the user wants to end the call."""
        logger.info(f"📞 Ending call for {self.phone_number}")

        # Wait for the agent to finish its current spoken response before hanging up.
        # IMPORTANT: Use ctx.wait_for_playout() — NOT ctx.session.current_speech.wait_for_playout()
        # The latter creates a circular wait (speech waits for tool, tool waits for speech).
        await ctx.wait_for_playout()

        await self.hangup()


# ────────────────────────────────────────────────────────────────────
# 5. ENTRYPOINT — Called by LiveKit when a job is dispatched
# ────────────────────────────────────────────────────────────────────

async def entrypoint(ctx: JobContext):
    """
    Main entry point for each outbound call.

    Flow:
    1. Connect to the LiveKit room
    2. Parse the phone number from dispatch metadata
    3. Set up the fully-streaming voice pipeline
    4. Start the agent session BEFORE dialing (so we don't miss audio)
    5. Dial the phone number via SIP
    6. Monitor call duration for cost protection
    7. Log the call to Airtable when it ends
    """
    logger.info(f"🏠 Connecting to room: {ctx.room.name}")
    await ctx.connect()

    # ── Parse dispatch metadata ──
    # When you dispatch a call, you pass metadata like:
    # {"phone_number": "+919876543210", "contact_name": "Rahul"}
    try:
        dial_info = json.loads(ctx.job.metadata) if ctx.job.metadata else {}
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON in job metadata")
        ctx.shutdown()
        return

    phone_number = dial_info.get("phone_number", "")
    contact_name = dial_info.get("contact_name", "the customer")

    if not phone_number:
        logger.error("❌ No phone_number in dispatch metadata")
        ctx.shutdown()
        return

    if not OUTBOUND_TRUNK_ID:
        logger.error("❌ SIP_OUTBOUND_TRUNK_ID not configured in .env")
        ctx.shutdown()
        return

    participant_identity = phone_number
    logger.info(f"📱 Preparing to call: {phone_number} (contact: {contact_name})")

    # ── Create the agent ──
    agent = RealEstateAgent(phone_number=phone_number)
    agent.call_start_time = time.time()

    # ────────────────────────────────────────────────────────────
    # 6. VOICE PIPELINE CONFIGURATION (fully streaming, low latency)
    # ────────────────────────────────────────────────────────────

    # Silero VAD — Voice Activity Detection
    # These parameters control when the agent thinks the user is speaking
    # vs. silent. Tune these for your use case:
    vad = silero.VAD.load(
        # Minimum duration of audio that counts as "speech" (in seconds).
        # Too low = noise/breathing triggers speech detection.
        # Too high = short words like "yes" or "no" get missed.
        # Recommended: 0.05 to 0.15
        min_speech_duration=0.06,

        # How long to wait after speech stops before deciding the user is done talking.
        # Too low = agent cuts the user off mid-sentence during pauses.
        # Too high = awkward silence before the agent responds.
        # Recommended: 0.4 to 0.7 for phone conversations.
        min_silence_duration=0.45,

        # Audio padding added BEFORE detected speech starts.
        # This captures the beginning of words that might otherwise be clipped.
        # Higher = safer but slightly more processing.
        # Recommended: 0.3 to 0.6
        prefix_padding_duration=0.3,

        # Probability threshold (0 to 1) for classifying audio as speech.
        # Lower = more sensitive (catches quiet speech but more false positives).
        # Higher = less sensitive (misses quiet speech but fewer false triggers).
        # Recommended: 0.4 to 0.6
        activation_threshold=0.45,

        # Audio sample rate in Hz. Use 16000 for telephony (standard).
        sample_rate=16000,
    )

    # The AgentSession orchestrates the full streaming pipeline:
    #   User speaks → Sarvam STT (streaming) → Groq LLM (streaming) → Sarvam TTS (streaming) → User hears
    #
    # LATENCY OPTIMIZATION:
    # - STT streams partial transcripts as the user speaks
    # - LLM starts generating as soon as the user finishes (first token < 200ms on Groq)
    # - TTS starts synthesizing audio from the FIRST LLM tokens, not the full response
    # - This means the user hears the agent start speaking almost immediately
    #
    # BARGE-IN / INTERRUPTION:
    # - If the user speaks while the agent is talking, the agent stops immediately
    # - This is the default behavior in AgentSession (allow_interruptions=True)
    session = AgentSession(
        vad=vad,

        # Sarvam STT — Speech-to-Text (streaming)
        # Saaras v3 is the most advanced model with best accuracy for Indian English
        stt=sarvam.STT(
            model="saaras:v3",
            language="en-IN",           # English-India accent optimized
            mode="transcribe",
        ),

        # Groq LLM — Language Model (streaming)
        # llama-3.3-70b-versatile offers the best balance of speed and quality
        # Groq's LPU hardware delivers ~200ms time-to-first-token
        llm=groq.LLM(
            model="llama-3.3-70b-versatile",
            temperature=0.7,            # Slightly creative but mostly focused
        ),

        # Sarvam TTS — Text-to-Speech (streaming)
        # Bulbul v3 with "rahul" voice for professional male Indian English
        # tts=sarvam.TTS(
        #     model="bulbul:v3",
        #     target_language_code="en-IN",
        # ),
        tts = sarvam.TTS(
            model="bulbul:v3",
            target_language_code="en-IN",
            speaker="shubh",
        ),
    )

    # ── Hook into transcript events ──
    # These fire whenever the user or agent finishes a turn.
    # We use them to build the full call transcript.

    @session.on("user_input_transcribed")
    def on_user_speech(ev):
        """Called when the user finishes a sentence."""
        if getattr(ev, "is_final", False):
            text = getattr(ev, "transcript", "")
            agent.transcript_lines.append(f"Caller: {text}")
            logger.info(f"🗣️ Caller: {text}")

    @session.on("conversation_item_added")
    def on_agent_speech(ev):
        """Called when a new item is added to the conversation, including agent responses."""
        msg = getattr(ev, "item", None)
        if msg and getattr(msg, "role", None) == "assistant":
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                text = " ".join([str(c) for c in content if isinstance(c, str)])
            else:
                text = str(content)
            agent.transcript_lines.append(f"Agent (Anand): {text}")
            logger.info(f"🤖 Agent: {text}")

    # ── Start the session BEFORE dialing ──
    # This ensures the agent is ready to listen immediately when the call connects.
    # If we started the session after the call connected, we might miss the
    # first few words the user says.
    session_started = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room,
        )
    )

    # ── Dial the phone number via SIP ──
    # This tells LiveKit to place an outbound call through the Twilio SIP trunk
    try:
        logger.info(f"📞 Dialing {phone_number}...")
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=OUTBOUND_TRUNK_ID,
                sip_call_to=phone_number,
                participant_identity=participant_identity,
                # Block until the person actually picks up the phone
                wait_until_answered=True,
            )
        )

        # Wait for both the session and the participant to be ready
        await session_started
        participant = await ctx.wait_for_participant(identity=participant_identity)
        logger.info(f"✅ Call connected: {participant.identity}")

        agent.set_participant(participant)
        agent.call_start_time = time.time()

        # ── PROACTIVE GREETING — eliminate initial silence ──
        # Without this, the agent waits for the user to speak first,
        # creating an awkward silence after the call connects.
        # generate_reply sends the greeting immediately through the
        # full pipeline (LLM → TTS → audio), so the caller hears
        # the agent within ~1 second of picking up.
        await session.generate_reply(
            instructions=f"The caller just picked up. Greet them warmly and briefly. "
            f"Their name is {contact_name}. Say something like: "
            f"'Hi {contact_name}, this is Anand from Horizon Realty. "
            f"Am I speaking with {contact_name}?' Keep it under 15 words."
        )

    except api.TwirpError as e:
        # SIP errors (number busy, no answer, invalid number, etc.)
        logger.error(
            f"❌ SIP call failed: {e.message}, "
            f"SIP status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()
        return
    except Exception as e:
        logger.error(f"❌ Unexpected error placing call: {e}")
        ctx.shutdown()
        return

    # ────────────────────────────────────────────────────────────
    # 7. COST PROTECTION — Maximum call duration limiter
    # ────────────────────────────────────────────────────────────

    async def enforce_max_duration():
        """
        Background task that monitors call duration.
        If the call exceeds MAX_CALL_DURATION, the agent politely
        ends the call to prevent runaway API costs.
        """
        await asyncio.sleep(MAX_CALL_DURATION)
        logger.warning(f"⏰ Call exceeded {MAX_CALL_DURATION}s limit — ending call")

        try:
            await session.generate_reply(
                instructions="Politely tell the caller that you need to wrap up this call now, "
                "and that a team member from Horizon Realty will follow up with them shortly. "
                "Thank them for their time."
            )
            # Give the goodbye message time to play
            await asyncio.sleep(5)
        except Exception:
            pass

        try:
            await agent.hangup()
        except Exception:
            pass

    duration_task = asyncio.create_task(enforce_max_duration())

    # ────────────────────────────────────────────────────────────
    # 8. WAIT FOR CALL TO END & LOG TO AIRTABLE
    # ────────────────────────────────────────────────────────────

    # Monitor for the participant disconnecting (call ended)
    disconnect_event = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def on_participant_left(p: rtc.RemoteParticipant):
        if p.identity == participant_identity:
            logger.info(f"📴 Caller disconnected: {p.identity}")
            disconnect_event.set()

    # Also monitor room disconnection
    @ctx.room.on("disconnected")
    def on_room_disconnected():
        logger.info("📴 Room disconnected")
        disconnect_event.set()

    # Wait for the call to end (either participant hangs up, or max duration reached)
    await disconnect_event.wait()

    # Cancel the duration limiter if it's still running
    duration_task.cancel()

    # Calculate call duration
    call_duration = time.time() - agent.call_start_time

    # Build the full transcript
    full_transcript = "\n".join(agent.transcript_lines) if agent.transcript_lines else "(no transcript captured)"

    logger.info(f"📊 Call summary: {phone_number}, duration={round(call_duration)}s, transcript_lines={len(agent.transcript_lines)}")

    # Log to Airtable (error-isolated — won't crash if it fails)
    log_call_to_airtable(
        caller_number=phone_number,
        duration_seconds=call_duration,
        transcript=full_transcript,
    )


# ────────────────────────────────────────────────────────────────────
# 9. FASTAPI HTTP ENDPOINT — Trigger outbound calls via REST API
# ────────────────────────────────────────────────────────────────────

# FastAPI app for triggering calls from external systems
app = FastAPI(
    title="Horizon Realty Voice Agent API",
    description="Trigger outbound qualification calls via REST API",
)


class CallRequest(BaseModel):
    """Request body for triggering an outbound call."""
    phone_number: str           # Phone number to call (e.g., "+919876543210")
    contact_name: str = ""      # Optional: name of the person being called


@app.post("/make-call")
async def make_call(request: CallRequest):
    """
    Trigger an outbound call to qualify a real estate lead.

    This endpoint dispatches the voice agent to call the specified phone number.
    The agent will have a natural conversation and log the results to Airtable.

    Example:
        POST /make-call
        {
            "phone_number": "+918080696109",
            "contact_name": "Yash"
        }
    """
    if not request.phone_number:
        raise HTTPException(status_code=400, detail="phone_number is required")

    if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")

    if not OUTBOUND_TRUNK_ID:
        raise HTTPException(status_code=500, detail="SIP_OUTBOUND_TRUNK_ID not configured")

    try:
        # Create a LiveKit API client
        lk_api = api.LiveKitAPI(
            url=LIVEKIT_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        )

        # Dispatch the agent to a new room with the phone number as metadata
        metadata = json.dumps({
            "phone_number": request.phone_number,
            "contact_name": request.contact_name,
        })

        # Create an agent dispatch — this triggers the entrypoint function
        await lk_api.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name="real-estate-agent",
                room=f"call-{request.phone_number.replace('+', '')}-{int(time.time())}",
                metadata=metadata,
            )
        )

        await lk_api.aclose()

        return JSONResponse(
            status_code=200,
            content={
                "status": "dispatched",
                "phone_number": request.phone_number,
                "contact_name": request.contact_name,
                "message": "Call has been dispatched. The agent will dial the number shortly.",
            },
        )

    except Exception as e:
        logger.error(f"❌ Failed to dispatch call: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to dispatch call: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint to verify the API is running."""
    return {
        "status": "healthy",
        "agent": "real-estate-agent",
        "max_call_duration": MAX_CALL_DURATION,
    }


def start_api_server():
    """Run the FastAPI server in a background thread."""
    uvicorn.run(app, host="0.0.0.0", port=API_PORT, log_level="info")


# ────────────────────────────────────────────────────────────────────
# 10. MAIN — Start the LiveKit agent worker + FastAPI server
# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start the FastAPI server in a background thread so it runs
    # alongside the LiveKit agent worker
    api_thread = threading.Thread(target=start_api_server, daemon=True)
    api_thread.start()
    logger.info(f"🌐 FastAPI server started on port {API_PORT}")

    # Start the LiveKit agent worker — this is the main blocking call
    # It connects to LiveKit Cloud and waits for dispatched jobs
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="real-estate-agent",
        )
    )


# """
# Real Estate AI Outbound Voice Agent
# A self-hosted outbound voice agent using LiveKit Agents framework.
# Pipeline: Sarvam STT→Groq LLM→Sarvam TTS
# VAD:Silero (tunable parameters below)
# Calls:Twilio via LiveKit SIP trunking
# Logging:Airtable (call_logs table)
# Trigger:FastAPI HTTP endpoint + lk CLI dispatch
# Author:Horizon Realty Engineering
# """

# from __future__ import annotations

# import asyncio
# import logging
# import json
# import os
# import time
# from datetime import datetime, timezone
# from typing import Any

# from dotenv import load_dotenv
# from livekit import rtc, api
# from livekit.agents import (
#     AgentSession,
#     Agent,
#     JobContext,
#     function_tool,
#     RunContext,
#     get_job_context,
#     cli,
#     WorkerOptions,
#     RoomInputOptions,
# )
# from livekit.plugins import silero, sarvam, groq

# # ─── FastAPI for HTTP call triggering ───
# from fastapi import FastAPI, HTTPException
# from fastapi.responses import JSONResponse
# from pydantic import BaseModel
# import uvicorn
# import threading

# # ─── Airtable for call logging ───
# from pyairtable import Table

# # ────────────────────────────────────────────────────────────────────
# # 1. ENVIRONMENT CONFIGURATION
# # ────────────────────────────────────────────────────────────────────
# # Load environment variables from .env file (never hardcode secrets!)
# load_dotenv(dotenv_path=".env.local")

# # Set up logging so we can trace what's happening during calls
# logger = logging.getLogger("real-estate-agent")
# logger.setLevel(logging.INFO)

# # ── LiveKit Cloud connection ──
# LIVEKIT_URL = os.getenv("LIVEKIT_URL")                  # Your LiveKit Cloud WebSocket URL
# LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")           # API key from LiveKit dashboard
# LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")     # API secret from LiveKit dashboard

# # ── SIP / Twilio outbound trunk ──
# OUTBOUND_TRUNK_ID = os.getenv("SIP_OUTBOUND_TRUNK_ID")  # Trunk ID for outbound calls via Twilio

# # ── Airtable logging ──
# AIRTABLE_PAT = os.getenv("AIRTABLE_PAT")                # Airtable Personal Access Token
# AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")        # Airtable Base ID
# AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "call_logs")  # Table name (defaults to call_logs)

# # ── Cost protection ──
# # Maximum call duration in seconds — prevents runaway costs from stuck calls
# MAX_CALL_DURATION = int(os.getenv("MAX_CALL_DURATION_SECONDS", "600"))  # Default: 10 minutes

# # ── FastAPI server port for HTTP call triggering ──
# API_PORT = int(os.getenv("API_PORT", "8081"))

# # ────────────────────────────────────────────────────────────────────
# # 2. SYSTEM PROMPT — Real Estate Buyer Qualification Agent
# # ────────────────────────────────────────────────────────────────────
# SYSTEM_PROMPT = """
# You are Anand, a professional real estate agent from Horizon Realty.

# Your goal is to qualify property buyers through a natural, human-like phone conversation and classify them as HOT, WARM, or COLD leads.

# This is a VOICE conversation:
# - Keep responses VERY SHORT (under 12 words unless needed)
# - Speak naturally like a real person
# - Ask only ONE question at a time
# - Acknowledge before asking next

# =========================
# FLOW
# =========================

# 1. GREETING
# - Confirm identity
# - Mention their property interest
# - Ask if they can talk now
# - If busy → schedule callback

# 2. INTEREST
# - Are they actively looking?
# - If not → politely end
# - If browsing → continue gently

# 3. QUALIFICATION (BANT)

# BUDGET → Ask range (suggest if hesitant)  
# AUTHORITY → Decision maker? Anyone else involved?  
# NEED → Property type + location + loan requirement  
# TIMELINE → When planning to buy?

# 4. BEHAVIOR
# - Adapt to user tone (excited, confused, hesitant)
# - Be polite, confident, and human
# - Never sound robotic

# =========================
# RULES
# =========================
# - Keep responses short and conversational
# - Do NOT ask multiple questions together
# - Do NOT repeat yourself
# - Gently steer back if off-topic
# - If unsure → say a specialist will follow up
# - NEVER hallucinate property details
# - End call using end_call tool when done
# """.strip()


# # ────────────────────────────────────────────────────────────────────
# # 3. AIRTABLE LOGGING (error-isolated)
# # ────────────────────────────────────────────────────────────────────

# def log_call_to_airtable(
#     caller_number: str,
#     duration_seconds: float,
#     transcript: str,
# ) -> None:
#     """
#     Log call details to Airtable after the call ends.

#     This runs in a try/except block so that if Airtable is down or
#     misconfigured, the call itself does NOT crash. We just log the
#     error and move on.
#     """
#     try:
#         # Validate that Airtable credentials are set
#         if not all([AIRTABLE_PAT, AIRTABLE_BASE_ID]):
#             logger.warning("⚠️ Airtable credentials not configured — skipping call log")
#             return

#         # Connect to the Airtable table
#         table = Table(AIRTABLE_PAT, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

#         # Insert a new record with the call details
#         table.create({
#             "caller_number": caller_number,
#             "duration_seconds": round(duration_seconds),
#             "transcript": transcript,
#             "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
#         })

#         logger.info(f"✅ Call logged to Airtable — {caller_number}, {round(duration_seconds)}s")

#     except Exception as e:
#         # IMPORTANT: We catch ALL exceptions here so logging failures
#         # never bring down the voice agent or crash an active call
#         logger.error(f"❌ Failed to log call to Airtable: {e}")


# # ────────────────────────────────────────────────────────────────────
# # 4. REAL ESTATE AGENT CLASS
# # ────────────────────────────────────────────────────────────────────

# class RealEstateAgent(Agent):
#     """
#     The AI voice agent that handles the conversation with the caller.
#     Inherits from LiveKit's Agent class and uses function tools for
#     call control actions.
#     """

#     def __init__(self, *, phone_number: str):
#         super().__init__(instructions=SYSTEM_PROMPT)

#         # Track the remote participant (the person on the phone)
#         self.participant: rtc.RemoteParticipant | None = None
#         self.phone_number = phone_number

#         # Transcript accumulator — we build this during the call
#         self.transcript_lines: list[str] = []
#         self.call_start_time: float = 0.0

#     def set_participant(self, participant: rtc.RemoteParticipant):
#         """Store reference to the phone participant once they join the room."""
#         self.participant = participant

#     async def hangup(self):
#         """
#         Hang up the call by deleting the LiveKit room.
#         This disconnects all participants and ends the SIP session.
#         """
#         job_ctx = get_job_context()
#         await job_ctx.api.room.delete_room(
#             api.DeleteRoomRequest(room=job_ctx.room.name)
#         )

#     @function_tool()
#     async def end_call(self, ctx: RunContext):
#         """Called when the conversation is complete or the user wants to end the call."""
#         logger.info(f"📞 Ending call for {self.phone_number}")

#         # Wait for the agent to finish its current response before hanging up
#         current_speech = ctx.session.current_speech
#         if current_speech:
#             await current_speech.wait_for_playout()

#         await self.hangup()


# # ────────────────────────────────────────────────────────────────────
# # 5. ENTRYPOINT — Called by LiveKit when a job is dispatched
# # ────────────────────────────────────────────────────────────────────

# async def entrypoint(ctx: JobContext):
#     """
#     Main entry point for each outbound call.

#     Flow:
#     1. Connect to the LiveKit room
#     2. Parse the phone number from dispatch metadata
#     3. Set up the fully-streaming voice pipeline
#     4. Start the agent session BEFORE dialing (so we don't miss audio)
#     5. Dial the phone number via SIP
#     6. Monitor call duration for cost protection
#     7. Log the call to Airtable when it ends
#     """
#     logger.info(f"🏠 Connecting to room: {ctx.room.name}")
#     await ctx.connect()

#     # ── Parse dispatch metadata ──
#     # When you dispatch a call, you pass metadata like:
#     # {"phone_number": "+919876543210", "contact_name": "Rahul"}
#     try:
#         dial_info = json.loads(ctx.job.metadata) if ctx.job.metadata else {}
#     except json.JSONDecodeError:
#         logger.error("❌ Invalid JSON in job metadata")
#         ctx.shutdown()
#         return

#     phone_number = dial_info.get("phone_number", "")
#     contact_name = dial_info.get("contact_name", "the customer")

#     if not phone_number:
#         logger.error("❌ No phone_number in dispatch metadata")
#         ctx.shutdown()
#         return

#     if not OUTBOUND_TRUNK_ID:
#         logger.error("❌ SIP_OUTBOUND_TRUNK_ID not configured in .env")
#         ctx.shutdown()
#         return

#     participant_identity = phone_number
#     logger.info(f"📱 Preparing to call: {phone_number} (contact: {contact_name})")

#     # ── Create the agent ──
#     agent = RealEstateAgent(phone_number=phone_number)
#     agent.call_start_time = time.time()

#     # ────────────────────────────────────────────────────────────
#     # 6. VOICE PIPELINE CONFIGURATION (fully streaming, low latency)
#     # ────────────────────────────────────────────────────────────

#     # Silero VAD — Voice Activity Detection
#     # These parameters control when the agent thinks the user is speaking
#     # vs. silent. Tune these for your use case:
#     vad = silero.VAD.load(
#         # Minimum duration of audio that counts as "speech" (in seconds).
#         # Too low = noise/breathing triggers speech detection.
#         # Too high = short words like "yes" or "no" get missed.
#         # Recommended: 0.05 to 0.15
#         min_speech_duration= 0.05,  # 0.08,

#         # How long to wait after speech stops before deciding the user is done talking.
#         # Too low = agent cuts the user off mid-sentence during pauses.
#         # Too high = awkward silence before the agent responds.
#         # Recommended: 0.4 to 0.7 for phone conversations.
#         min_silence_duration= 0.35, #0.55,

#         # Audio padding added BEFORE detected speech starts.
#         # This captures the beginning of words that might otherwise be clipped.
#         # Higher = safer but slightly more processing.
#         # Recommended: 0.3 to 0.6
#         prefix_padding_duration=0.3,#0.4,

#         # Probability threshold (0 to 1) for classifying audio as speech.
#         # Lower = more sensitive (catches quiet speech but more false positives).
#         # Higher = less sensitive (misses quiet speech but fewer false triggers).
#         # Recommended: 0.4 to 0.6
#         activation_threshold=0.45, #0.5,

#         # Audio sample rate in Hz. Use 16000 for telephony (standard).
#         sample_rate=16000,
#     )

#     # The AgentSession orchestrates the full streaming pipeline:
#     #   User speaks → Sarvam STT (streaming) → Groq LLM (streaming) → Sarvam TTS (streaming) → User hears
#     #
#     # LATENCY OPTIMIZATION:
#     # - STT streams partial transcripts as the user speaks
#     # - LLM starts generating as soon as the user finishes (first token < 200ms on Groq)
#     # - TTS starts synthesizing audio from the FIRST LLM tokens, not the full response
#     # - This means the user hears the agent start speaking almost immediately
#     #
#     # BARGE-IN / INTERRUPTION:
#     # - If the user speaks while the agent is talking, the agent stops immediately
#     # - This is the default behavior in AgentSession (allow_interruptions=True)
#     session = AgentSession(
#         vad=vad,

#         # Sarvam STT — Speech-to-Text (streaming)
#         # Saaras v3 is the most advanced model with best accuracy for Indian English
#         stt=sarvam.STT(
#             model="saaras:v3",
#             language="en-IN",           # English-India accent optimized
#             mode="transcribe",
#         ),

#         # Groq LLM — Language Model (streaming)
#         # llama-3.3-70b-versatile offers the best balance of speed and quality
#         # Groq's LPU hardware delivers ~200ms time-to-first-token
#         llm=groq.LLM(
#             model="llama-3.3-70b-versatile",
#             temperature=0.3, #0.7,            # Slightly creative but mostly focused
#         ),

#         # Sarvam TTS — Text-to-Speech (streaming)
#         # Bulbul v3 with "rahul" voice for professional male Indian English
#         # tts = sarvam.TTS(
#         #     model="bulbul:v3",
#         #     target_language_code="en-IN",
#         #     speaker="shubh",
#         # ),

#         tts = sarvam.TTS(
#             model="bulbul:v3",
#             target_language_code="en-IN",
#             speaker="shubh",
#             min_buffer_size=30,   # 🔥 reduce from default 50
#             max_chunk_length=100  # 🔥 reduce from 150
#         ),
#     )

#     # ── Hook into transcript events ──
#     # These fire whenever the user or agent finishes a turn.
#     # We use them to build the full call transcript.

#     @session.on("user_speech_committed")
#     def on_user_speech(msg):
#         """Called when the user finishes a sentence."""
#         text = msg.content if hasattr(msg, 'content') else str(msg)
#         agent.transcript_lines.append(f"Caller: {text}")
#         logger.info(f"🗣️ Caller: {text}")

#     @session.on("agent_speech_committed")
#     def on_agent_speech(msg):
#         """Called when the agent finishes a response."""
#         text = msg.content if hasattr(msg, 'content') else str(msg)
#         agent.transcript_lines.append(f"Agent (Anand): {text}")
#         logger.info(f"🤖 Agent: {text}")

#     # ── Start the session BEFORE dialing ──
#     # This ensures the agent is ready to listen immediately when the call connects.
#     # If we started the session after the call connected, we might miss the
#     # first few words the user says.
#     session_started = asyncio.create_task(
#         session.start(
#             agent=agent,
#             room=ctx.room,
#         )
#     )

#     # ── Dial the phone number via SIP ──
#     # This tells LiveKit to place an outbound call through the Twilio SIP trunk
#     try:
#         logger.info(f"📞 Dialing {phone_number}...")
#         await ctx.api.sip.create_sip_participant(
#             api.CreateSIPParticipantRequest(
#                 room_name=ctx.room.name,
#                 sip_trunk_id=OUTBOUND_TRUNK_ID,
#                 sip_call_to=phone_number,
#                 participant_identity=participant_identity,
#                 # Block until the person actually picks up the phone
#                 wait_until_answered=True,
#             )
#         )

#         # Wait for both the session and the participant to be ready
#         await session_started
#         participant = await ctx.wait_for_participant(identity=participant_identity)
#         logger.info(f"✅ Call connected: {participant.identity}")

#         agent.set_participant(participant)
#         agent.call_start_time = time.time()

#     except api.TwirpError as e:
#         # SIP errors (number busy, no answer, invalid number, etc.)
#         logger.error(
#             f"❌ SIP call failed: {e.message}, "
#             f"SIP status: {e.metadata.get('sip_status_code')} "
#             f"{e.metadata.get('sip_status')}"
#         )
#         ctx.shutdown()
#         return
#     except Exception as e:
#         logger.error(f"❌ Unexpected error placing call: {e}")
#         ctx.shutdown()
#         return

#     # ────────────────────────────────────────────────────────────
#     # 7. COST PROTECTION — Maximum call duration limiter
#     # ────────────────────────────────────────────────────────────

#     async def enforce_max_duration():
#         """
#         Background task that monitors call duration.
#         If the call exceeds MAX_CALL_DURATION, the agent politely
#         ends the call to prevent runaway API costs.
#         """
#         await asyncio.sleep(MAX_CALL_DURATION)
#         logger.warning(f"⏰ Call exceeded {MAX_CALL_DURATION}s limit — ending call")

#         try:
#             await session.generate_reply(
#                 instructions="Respond in 1 short sentence only."
#                 # instructions="Politely tell the caller that you need to wrap up this call now, "
#                 # "and that a team member from Horizon Realty will follow up with them shortly. "
#                 # "Thank them for their time."
#             )
#             # Give the goodbye message time to play
#             await asyncio.sleep(5)
#         except Exception:
#             pass

#         try:
#             await agent.hangup()
#         except Exception:
#             pass

#     duration_task = asyncio.create_task(enforce_max_duration())

#     # ────────────────────────────────────────────────────────────
#     # 8. WAIT FOR CALL TO END & LOG TO AIRTABLE
#     # ────────────────────────────────────────────────────────────

#     # Monitor for the participant disconnecting (call ended)
#     disconnect_event = asyncio.Event()

#     @ctx.room.on("participant_disconnected")
#     def on_participant_left(p: rtc.RemoteParticipant):
#         if p.identity == participant_identity:
#             logger.info(f"📴 Caller disconnected: {p.identity}")
#             disconnect_event.set()

#     # Also monitor room disconnection
#     @ctx.room.on("disconnected")
#     def on_room_disconnected():
#         logger.info("📴 Room disconnected")
#         disconnect_event.set()

#     # Wait for the call to end (either participant hangs up, or max duration reached)
#     await disconnect_event.wait()

#     # Cancel the duration limiter if it's still running
#     duration_task.cancel()

#     # Calculate call duration
#     call_duration = time.time() - agent.call_start_time

#     # Build the full transcript
#     full_transcript = "\n".join(agent.transcript_lines) if agent.transcript_lines else "(no transcript captured)"

#     logger.info(f"📊 Call summary: {phone_number}, duration={round(call_duration)}s, transcript_lines={len(agent.transcript_lines)}")

#     # Log to Airtable (error-isolated — won't crash if it fails)
#     log_call_to_airtable(
#         caller_number=phone_number,
#         duration_seconds=call_duration,
#         transcript=full_transcript,
#     )


# # ────────────────────────────────────────────────────────────────────
# # 9. FASTAPI HTTP ENDPOINT — Trigger outbound calls via REST API
# # ────────────────────────────────────────────────────────────────────

# # FastAPI app for triggering calls from external systems
# app = FastAPI(
#     title="Horizon Realty Voice Agent API",
#     description="Trigger outbound qualification calls via REST API",
# )


# class CallRequest(BaseModel):
#     """Request body for triggering an outbound call."""
#     phone_number: str           # Phone number to call (e.g., "+919876543210")
#     contact_name: str = ""      # Optional: name of the person being called


# @app.post("/make-call")
# async def make_call(request: CallRequest):
#     """
#     Trigger an outbound call to qualify a real estate lead.

#     This endpoint dispatches the voice agent to call the specified phone number.
#     The agent will have a natural conversation and log the results to Airtable.

#     Example:
#         POST /make-call
#         {
#             "phone_number": "+918080696109",
#             "contact_name": "Yash"
#         }
#     """
#     if not request.phone_number:
#         raise HTTPException(status_code=400, detail="phone_number is required")

#     if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
#         raise HTTPException(status_code=500, detail="LiveKit credentials not configured")

#     if not OUTBOUND_TRUNK_ID:
#         raise HTTPException(status_code=500, detail="SIP_OUTBOUND_TRUNK_ID not configured")

#     try:
#         # Create a LiveKit API client
#         lk_api = api.LiveKitAPI(
#             url=LIVEKIT_URL,
#             api_key=LIVEKIT_API_KEY,
#             api_secret=LIVEKIT_API_SECRET,
#         )

#         # Dispatch the agent to a new room with the phone number as metadata
#         metadata = json.dumps({
#             "phone_number": request.phone_number,
#             "contact_name": request.contact_name,
#         })

#         # Create an agent dispatch — this triggers the entrypoint function
#         await lk_api.agent_dispatch.create_dispatch(
#             api.CreateAgentDispatchRequest(
#                 agent_name="real-estate-agent",
#                 room=f"call-{request.phone_number.replace('+', '')}-{int(time.time())}",
#                 metadata=metadata,
#             )
#         )

#         await lk_api.aclose()

#         return JSONResponse(
#             status_code=200,
#             content={
#                 "status": "dispatched",
#                 "phone_number": request.phone_number,
#                 "contact_name": request.contact_name,
#                 "message": "Call has been dispatched. The agent will dial the number shortly.",
#             },
#         )

#     # except Exception as e:
#     #     logger.error(f"❌ Failed to dispatch call: {e}")
#     #     raise HTTPException(status_code=500, detail=f"Failed to dispatch call: {str(e)}")

#     except api.TwirpError as e:
#         sip_code = e.metadata.get("sip_status_code")

#         if sip_code == "486":
#             logger.warning(f"📵 User busy: {phone_number} — will retry later")
#         elif sip_code == "480":
#             logger.warning(f"📴 User unavailable: {phone_number}")
#         elif sip_code == "408":
#             logger.warning(f"⏳ No answer: {phone_number}")
#         else:
#             logger.error(f"❌ SIP call failed: {e.message}")

#         ctx.shutdown()
#         return


# @app.get("/health")
# async def health_check():
#     """Health check endpoint to verify the API is running."""
#     return {
#         "status": "healthy",
#         "agent": "real-estate-agent",
#         "max_call_duration": MAX_CALL_DURATION,
#     }


# def start_api_server():
#     """Run the FastAPI server in a background thread."""
#     uvicorn.run(app, host="0.0.0.0", port=API_PORT, log_level="info")


# # ────────────────────────────────────────────────────────────────────
# # 10. MAIN — Start the LiveKit agent worker + FastAPI server
# # ────────────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     # Start the FastAPI server in a background thread so it runs
#     # alongside the LiveKit agent worker
#     api_thread = threading.Thread(target=start_api_server, daemon=True)
#     api_thread.start()
#     logger.info(f"🌐 FastAPI server started on port {API_PORT}")

#     # Start the LiveKit agent worker — this is the main blocking call
#     # It connects to LiveKit Cloud and waits for dispatched jobs
#     cli.run_app(
#         # WorkerOptions(
#         #     entrypoint_fnc=entrypoint,
#         #     agent_name="real-estate-agent",
#         #     num_idle_processes=1   # 🔥 pre-warm worker
#         # )
#         WorkerOptions(
#             entrypoint_fnc=entrypoint,
#             agent_name="real-estate-agent",
#             num_idle_processes=1   # 🔥 pre-warm worker
#         )
#     )
