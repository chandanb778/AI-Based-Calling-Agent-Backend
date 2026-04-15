"""
Centralized configuration management using Pydantic Settings.

All environment variables are loaded once and validated at startup.
Import `settings` anywhere in the app to access configuration.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field

# ── Load .env.local for local dev (silently ignored if file doesn't exist) ──
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env.local"), override=False)


class Settings(BaseSettings):
    """
    Application-wide settings, validated and typed.
    Every field maps to an env var of the same name (case-insensitive).
    """

    # ── LiveKit ──
    livekit_url: str = Field(..., description="LiveKit Cloud WebSocket URL")
    livekit_api_key: str = Field(..., description="LiveKit API key")
    livekit_api_secret: str = Field(..., description="LiveKit API secret")

    # ── SIP / Twilio ──
    sip_outbound_trunk_id: str = Field(..., description="Twilio SIP trunk ID for outbound calls")

    # ── Sarvam AI ──
    sarvam_api_key: str = Field(..., description="Sarvam AI API key")

    # ── Groq LLM ──
    groq_api_key: str = Field(..., description="Groq API key")

    # ── Supabase (replaces Airtable) ──
    supabase_url: str = Field(default="", description="Supabase project URL")
    supabase_key: str = Field(default="", description="Supabase anon/service-role key")

    # ── Cost protection ──
    max_call_duration_seconds: int = Field(default=600, description="Max call duration before auto-hangup")

    # ── FastAPI ──
    api_port: int = Field(default=8000, description="FastAPI server port (overridden by $PORT on Railway)")
    api_host: str = Field(default="0.0.0.0", description="FastAPI server host")

    # ── Bulk calling ──
    bulk_max_concurrency: int = Field(default=5, description="Max parallel outbound calls in bulk mode")
    bulk_retry_max_attempts: int = Field(default=3, description="Max retry attempts per failed call")
    bulk_retry_base_delay: float = Field(default=2.0, description="Base delay (seconds) for exponential backoff")

    # ── Agent ──
    agent_name: str = Field(default="real-estate-agent", description="LiveKit agent name")

    # ── Logging ──
    log_level: str = Field(default="INFO", description="Logging level")

    model_config = {
        "env_file": ".env.local",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",          # Don't crash on unknown env vars
        "env_ignore_empty": True,   # Ignore empty env vars
    }


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# Convenience alias — `from app.config import settings`
settings = get_settings()
