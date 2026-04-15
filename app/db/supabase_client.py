"""
Supabase client wrapper.

Provides a lazy-initialized, reusable Supabase client.
The client is created on first access and reused thereafter.
"""

from __future__ import annotations

from typing import Optional

from supabase import create_client, Client

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_client: Optional[Client] = None


def get_supabase() -> Client:
    """
    Return a Supabase client (singleton).

    Raises RuntimeError if Supabase credentials are not configured.
    """
    global _client

    if _client is not None:
        return _client

    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError(
            "Supabase credentials not configured. "
            "Set SUPABASE_URL and SUPABASE_KEY in .env.local"
        )

    logger.info("🔌 Initializing Supabase client → %s", settings.supabase_url)
    _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


def is_supabase_configured() -> bool:
    """Check whether Supabase env vars are present (for health checks)."""
    return bool(settings.supabase_url and settings.supabase_key)
