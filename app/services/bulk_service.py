"""
Bulk calling service.

Implements an async, queue-based bulk calling system with:
- Semaphore-controlled concurrency (default 5 parallel calls)
- Exponential backoff retries for failed calls
- Per-job status tracking (pending / in-progress / completed / failed)
- Job ID-based status queries
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from app.config import settings
from app.models.schemas import (
    BulkContact,
    BulkCallItemStatus,
    BulkJobStatus,
    CallStatus,
)
from app.services.call_service import dispatch_call
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── In-memory job store ──
# In production you might back this with Redis or a DB table.
# For now, an in-process dict is sufficient and avoids external deps.
_jobs: dict[str, BulkJobStatus] = {}


def get_job(job_id: str) -> Optional[BulkJobStatus]:
    """Retrieve the current status of a bulk job."""
    return _jobs.get(job_id)


async def start_bulk_job(contacts: list[BulkContact]) -> str:
    """
    Create a new bulk calling job, store it, and kick off the
    background processing loop.

    Returns the job_id.
    """
    job_id = str(uuid.uuid4())

    # Store original contacts so we can access language later
    _contact_languages: dict[int, str] = {}

    contact_statuses = [
        BulkCallItemStatus(
            phone_number=c.phone_number,
            contact_name=c.contact_name,
            status=CallStatus.PENDING,
            attempts=0,
        )
        for c in contacts
    ]

    for i, c in enumerate(contacts):
        _contact_languages[i] = getattr(c, "language", "english")

    job = BulkJobStatus(
        job_id=job_id,
        total=len(contacts),
        pending=len(contacts),
        in_progress=0,
        completed=0,
        failed=0,
        contacts=contact_statuses,
    )

    _jobs[job_id] = job

    # Fire-and-forget the processing loop
    asyncio.create_task(_process_bulk_job(job_id, _contact_languages))

    logger.info(
        "📋 Bulk job %s created — %d contacts queued",
        job_id,
        len(contacts),
    )

    return job_id


async def _process_bulk_job(job_id: str, contact_languages: dict[int, str]) -> None:
    """
    Process all contacts in a bulk job with concurrency control
    and retry logic.
    """
    job = _jobs[job_id]
    semaphore = asyncio.Semaphore(settings.bulk_max_concurrency)

    tasks = [
        _call_with_retry(job, idx, semaphore, contact_languages.get(idx, "english"))
        for idx in range(len(job.contacts))
    ]

    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(
        "✅ Bulk job %s finished — completed=%d, failed=%d",
        job_id,
        job.completed,
        job.failed,
    )


async def _call_with_retry(
    job: BulkJobStatus,
    idx: int,
    semaphore: asyncio.Semaphore,
    language: str = "english",
) -> None:
    """
    Attempt to dispatch a single call within the bulk job,
    with exponential-backoff retries.
    """
    contact = job.contacts[idx]
    max_attempts = settings.bulk_retry_max_attempts
    base_delay = settings.bulk_retry_base_delay

    async with semaphore:
        contact.status = CallStatus.IN_PROGRESS
        _recount(job)

        for attempt in range(1, max_attempts + 1):
            contact.attempts = attempt
            try:
                await dispatch_call(
                    phone_number=contact.phone_number,
                    contact_name=contact.contact_name,
                    language=language,
                )
                contact.status = CallStatus.COMPLETED
                contact.error = None
                _recount(job)

                logger.info(
                    "✅ Bulk call %s → %s succeeded (attempt %d)",
                    job.job_id[:8],
                    contact.phone_number,
                    attempt,
                )
                return

            except Exception as e:
                delay = base_delay * (2 ** (attempt - 1))
                contact.error = str(e)
                logger.warning(
                    "⚠️  Bulk call %s → %s attempt %d/%d failed: %s (retry in %.1fs)",
                    job.job_id[:8],
                    contact.phone_number,
                    attempt,
                    max_attempts,
                    e,
                    delay,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(delay)

        # All attempts exhausted
        contact.status = CallStatus.FAILED
        _recount(job)
        logger.error(
            "❌ Bulk call %s → %s failed after %d attempts",
            job.job_id[:8],
            contact.phone_number,
            max_attempts,
        )


def _recount(job: BulkJobStatus) -> None:
    """Recalculate aggregate counters from individual contact statuses."""
    job.pending = sum(1 for c in job.contacts if c.status == CallStatus.PENDING)
    job.in_progress = sum(1 for c in job.contacts if c.status == CallStatus.IN_PROGRESS)
    job.completed = sum(1 for c in job.contacts if c.status == CallStatus.COMPLETED)
    job.failed = sum(1 for c in job.contacts if c.status == CallStatus.FAILED)
