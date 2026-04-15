"""
Database operations for leads.

All Supabase queries for the leads table are isolated here.
Error-isolated: failures never crash the voice agent.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.db.supabase_client import get_supabase, is_supabase_configured
from app.utils.logger import get_logger

logger = get_logger(__name__)

TABLE = "leads"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0


async def insert_lead(lead_data: dict) -> Optional[dict]:
    """
    Insert a lead into Supabase with retry logic.

    Error-isolated: returns None on failure, never crashes.
    """
    if not is_supabase_configured():
        logger.warning("⚠️  Supabase not configured — skipping lead insert")
        return None

    record = {
        "id": str(uuid.uuid4()),
        "name": lead_data.get("name", "unknown"),
        "phone": lead_data.get("phone", "unknown"),
        "budget": lead_data.get("budget", "unknown"),
        "location": lead_data.get("location", "unknown"),
        "property_type": lead_data.get("property_type", "unknown"),
        "timeline": lead_data.get("timeline", "unknown"),
        "loan_required": lead_data.get("loan_required", "unknown"),
        "decision_maker": lead_data.get("decision_maker", "unknown"),
        "lead_score": lead_data.get("lead_score", "COLD"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            supabase = get_supabase()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: supabase.table(TABLE).insert(record).execute(),
            )

            if result.data:
                logger.info(
                    "✅ Lead saved — %s, score=%s, id=%s",
                    record["phone"],
                    record["lead_score"],
                    record["id"],
                )
                return result.data[0]
            else:
                logger.error("❌ Supabase lead insert returned empty data")

        except Exception as e:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.error(
                "❌ Lead insert attempt %d/%d failed: %s (retrying in %.1fs)",
                attempt, MAX_RETRIES, e, delay,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(delay)

    logger.error("❌ All %d lead insert attempts failed", MAX_RETRIES)
    return None


async def get_leads(
    page: int = 1,
    page_size: int = 20,
    score: Optional[str] = None,
) -> tuple[list[dict], int]:
    """
    Fetch paginated leads, newest first.
    Optionally filter by lead_score (HOT, WARM, COLD).

    Returns (rows, total_count).
    """
    supabase = get_supabase()

    # Build count query
    count_query = supabase.table(TABLE).select("id", count="exact")
    if score:
        count_query = count_query.eq("lead_score", score.upper())

    count_result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: count_query.execute(),
    )
    total = count_result.count or 0

    # Build data query
    offset = (page - 1) * page_size
    data_query = (
        supabase.table(TABLE)
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
    )
    if score:
        data_query = data_query.eq("lead_score", score.upper())

    data_result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: data_query.execute(),
    )

    return data_result.data or [], total


async def get_lead_by_id(lead_id: str) -> Optional[dict]:
    """Fetch a single lead by UUID."""
    supabase = get_supabase()

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase.table(TABLE)
            .select("*")
            .eq("id", lead_id)
            .maybe_single()
            .execute(),
    )

    return result.data
