"""
Call dispatch service.

Handles the logic for dispatching a single outbound call
via the LiveKit Agent Dispatch API.
"""

from __future__ import annotations

import json
import time

from livekit import api

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def dispatch_call(phone_number: str, contact_name: str = "", language: str = "english") -> dict:
    """
    Dispatch a single outbound call through LiveKit.

    Creates a LiveKit room and dispatches the agent worker to it
    with the provided phone number, contact name, and language in metadata.

    Returns a dict with dispatch details.
    Raises on failure (caller is responsible for HTTP error mapping).
    """
    lk_api = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )

    metadata = json.dumps({
        "phone_number": phone_number,
        "contact_name": contact_name,
        "language": language,
    })

    room_name = f"call-{phone_number.replace('+', '')}-{int(time.time())}"

    try:
        await lk_api.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=settings.agent_name,
                room=room_name,
                metadata=metadata,
            )
        )

        logger.info("📞 Dispatched call → %s (room: %s, lang: %s)", phone_number, room_name, language)

        return {
            "status": "dispatched",
            "phone_number": phone_number,
            "contact_name": contact_name,
            "room_name": room_name,
            "message": f"Call has been dispatched in {language}. The agent will dial the number shortly.",
        }

    finally:
        await lk_api.aclose()
