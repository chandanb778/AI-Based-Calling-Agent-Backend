"""
API routes — all FastAPI endpoints.

Routes are thin: validate input, delegate to services, format output.
No business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.db import call_logs
from app.db import leads as leads_db
from app.db.supabase_client import is_supabase_configured
from app.models.schemas import (
    CallRequest,
    CallResponse,
    CallLogOut,
    PaginatedCallLogs,
    BulkCallRequest,
    BulkCallResponse,
    BulkJobStatus,
    HealthResponse,
    LeadOut,
    PaginatedLeads,
)
from app.services.call_service import dispatch_call
from app.services.bulk_service import start_bulk_job, get_job
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ───────────────────────────────────────────────────
# Health
# ───────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check — verifies the API is running and deps are reachable."""
    return HealthResponse(
        status="healthy",
        agent=settings.agent_name,
        max_call_duration=settings.max_call_duration_seconds,
        supabase_connected=is_supabase_configured(),
    )


# ───────────────────────────────────────────────────
# Single call
# ───────────────────────────────────────────────────

@router.post("/make-call", response_model=CallResponse)
async def make_call(request: CallRequest):
    """Dispatch a single outbound qualification call."""
    if not request.phone_number:
        raise HTTPException(status_code=400, detail="phone_number is required")

    if not all([settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret]):
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")

    if not settings.sip_outbound_trunk_id:
        raise HTTPException(status_code=500, detail="SIP_OUTBOUND_TRUNK_ID not configured")

    try:
        result = await dispatch_call(
            phone_number=request.phone_number,
            contact_name=request.contact_name,
            language=request.language,
        )
        return CallResponse(**result)

    except Exception as e:
        logger.error("❌ Failed to dispatch call: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to dispatch call: {str(e)}")


# ───────────────────────────────────────────────────
# Bulk calling
# ───────────────────────────────────────────────────

@router.post("/bulk-call", response_model=BulkCallResponse)
async def bulk_call(request: BulkCallRequest):
    """
    Dispatch calls to multiple contacts.

    Returns a job_id for tracking progress via GET /bulk-status/{job_id}.
    """
    if not all([settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret]):
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")

    if not settings.sip_outbound_trunk_id:
        raise HTTPException(status_code=500, detail="SIP_OUTBOUND_TRUNK_ID not configured")

    job_id = await start_bulk_job(request.contacts)

    return BulkCallResponse(
        job_id=job_id,
        total_contacts=len(request.contacts),
        message=f"Bulk job created. {len(request.contacts)} calls queued.",
    )


@router.get("/bulk-status/{job_id}", response_model=BulkJobStatus)
async def bulk_status(job_id: str):
    """Get the status of a bulk calling job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


# ───────────────────────────────────────────────────
# Call logs (frontend-ready)
# ───────────────────────────────────────────────────

@router.get("/calls", response_model=PaginatedCallLogs)
async def list_calls(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """
    Fetch paginated call logs (newest first).

    Query params:
      - page (int, default 1)
      - page_size (int, default 20, max 100)
    """
    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase not configured")

    try:
        rows, total = await call_logs.get_call_logs(page=page, page_size=page_size)
        return PaginatedCallLogs(
            total=total,
            page=page,
            page_size=page_size,
            data=[CallLogOut(**row) for row in rows],
        )
    except Exception as e:
        logger.error("❌ Failed to fetch call logs: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch call logs: {str(e)}")


@router.get("/calls/{call_id}", response_model=CallLogOut)
async def get_call(call_id: str):
    """Fetch a single call log by ID."""
    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase not configured")

    try:
        row = await call_logs.get_call_log_by_id(call_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
        return CallLogOut(**row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("❌ Failed to fetch call %s: %s", call_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch call: {str(e)}")


# ───────────────────────────────────────────────────
# Leads
# ───────────────────────────────────────────────────

@router.get("/leads", response_model=PaginatedLeads)
async def list_leads(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page"),
    score: str = Query(default="", description="Filter by lead_score: HOT, WARM, COLD"),
):
    """
    Fetch paginated leads (newest first).
    Optionally filter by ?score=HOT|WARM|COLD.
    """
    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase not configured")

    try:
        score_filter = score.upper() if score and score.upper() in ("HOT", "WARM", "COLD") else None
        rows, total = await leads_db.get_leads(
            page=page, page_size=page_size, score=score_filter,
        )
        return PaginatedLeads(
            total=total,
            page=page,
            page_size=page_size,
            data=[LeadOut(**row) for row in rows],
        )
    except Exception as e:
        logger.error("❌ Failed to fetch leads: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch leads: {str(e)}")


@router.get("/leads/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: str):
    """Fetch a single lead by ID."""
    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase not configured")

    try:
        row = await leads_db.get_lead_by_id(lead_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
        return LeadOut(**row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("❌ Failed to fetch lead %s: %s", lead_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch lead: {str(e)}")


# ───────────────────────────────────────────────────
# Lead backfill
# ───────────────────────────────────────────────────

@router.post("/backfill-leads")
async def backfill_leads():
    """
    Scan all call_logs in Supabase, run lead extraction on transcripts
    that don't already have a matching lead, and insert the results.

    This is idempotent — re-running it won't create duplicates.
    """
    import asyncio
    from app.db.supabase_client import get_supabase
    from app.services.lead_service import extract_lead_from_transcript

    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase not configured")

    try:
        supabase = get_supabase()

        # Fetch all call logs
        logs_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase.table("call_logs")
                .select("caller_number,transcript")
                .order("created_at", desc=True)
                .execute(),
        )
        call_logs = logs_result.data or []

        # Fetch existing lead phones to skip duplicates
        leads_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase.table("leads").select("phone").execute(),
        )
        existing_phones = set(row["phone"] for row in (leads_result.data or []))

        created = 0
        skipped = 0
        failed = 0

        for log in call_logs:
            phone = log.get("caller_number", "")
            transcript = log.get("transcript", "")

            if phone in existing_phones:
                skipped += 1
                continue

            if not transcript or transcript == "(no transcript captured)":
                skipped += 1
                continue

            try:
                lead_data = await extract_lead_from_transcript(
                    transcript=transcript,
                    phone_number=phone,
                    contact_name="",
                )
                if lead_data:
                    result = await leads_db.insert_lead(lead_data)
                    if result:
                        existing_phones.add(phone)
                        created += 1
                    else:
                        failed += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

            # Small delay for Groq rate limits
            await asyncio.sleep(1)

        return {
            "status": "completed",
            "total_logs": len(call_logs),
            "leads_created": created,
            "skipped": skipped,
            "failed": failed,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("❌ Backfill failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Backfill failed: {str(e)}")
