"""
Database operations for call logs.

All Supabase queries are isolated here.  If the DB is unreachable,
errors are caught and logged — they never crash the voice agent.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.db.supabase_client import get_supabase, is_supabase_configured
from app.utils.logger import get_logger

logger = get_logger(__name__)

TABLE = "call_logs"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds


async def insert_call_log(
    caller_number: str,
    duration_seconds: float,
    transcript: str,
) -> Optional[dict]:
    """
    Insert a call log into Supabase with retry logic.

    This is error-isolated: if Supabase is down or misconfigured,
    the calling code does NOT crash.  We log the error and return None.

    Returns the inserted row dict on success, None on failure.
    """
    if not is_supabase_configured():
        logger.warning("⚠️  Supabase not configured — skipping call log")
        return None

    record = {
        "id": str(uuid.uuid4()),
        "caller_number": caller_number,
        "duration_seconds": round(duration_seconds, 1),
        "transcript": transcript,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            supabase = get_supabase()
            # supabase-py is sync under the hood, run in executor to avoid blocking
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: supabase.table(TABLE).insert(record).execute(),
            )

            if result.data:
                logger.info(
                    "✅ Call logged to Supabase — %s, %ss, id=%s",
                    caller_number,
                    round(duration_seconds),
                    record["id"],
                )
                return result.data[0]
            else:
                logger.error("❌ Supabase insert returned empty data")

        except Exception as e:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.error(
                "❌ Supabase insert attempt %d/%d failed: %s (retrying in %.1fs)",
                attempt,
                MAX_RETRIES,
                e,
                delay,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(delay)

    logger.error("❌ All %d Supabase insert attempts failed for %s", MAX_RETRIES, caller_number)
    return None


async def get_call_logs(
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """
    Fetch paginated call logs, newest first.

    Returns (rows, total_count).
    """
    supabase = get_supabase()

    # Get total count
    count_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase.table(TABLE)
            .select("id", count="exact")
            .execute(),
    )
    total = count_result.count or 0

    # Fetch the requested page
    offset = (page - 1) * page_size
    data_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase.table(TABLE)
            .select("*")
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
            .execute(),
    )

    return data_result.data or [], total


async def get_call_log_by_id(call_id: str) -> Optional[dict]:
    """Fetch a single call log by UUID."""
    supabase = get_supabase()

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase.table(TABLE)
            .select("*")
            .eq("id", call_id)
            .maybe_single()
            .execute(),
    )

    return result.data
