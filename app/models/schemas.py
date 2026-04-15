"""
Pydantic models (schemas) for API requests, responses, and internal DTOs.

All data flowing through the system has a typed shape — no raw dicts
in business logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ───────────────────────────────────────────────────
# Call-related schemas
# ───────────────────────────────────────────────────

class CallRequest(BaseModel):
    """POST /make-call request body."""
    phone_number: str = Field(..., description="E.164 phone number, e.g. +919876543210")
    contact_name: str = Field(default="", description="Name of the person being called")
    language: str = Field(default="english", description="Call language: english, hindi, or marathi")


class CallResponse(BaseModel):
    """Standard response after dispatching a single call."""
    status: str
    phone_number: str
    contact_name: str
    message: str


class CallLogOut(BaseModel):
    """Serialized call log for API responses."""
    id: str
    caller_number: str
    duration_seconds: float
    transcript: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedCallLogs(BaseModel):
    """Paginated list of call logs."""
    total: int
    page: int
    page_size: int
    data: list[CallLogOut]


# ───────────────────────────────────────────────────
# Bulk calling schemas
# ───────────────────────────────────────────────────

class BulkContact(BaseModel):
    """A single contact in a bulk-call request."""
    phone_number: str
    contact_name: str = ""
    language: str = "english"


class BulkCallRequest(BaseModel):
    """POST /bulk-call request body."""
    contacts: list[BulkContact] = Field(..., min_length=1, max_length=500)


class CallStatus(str, Enum):
    """Status of an individual call within a bulk job."""
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    FAILED = "failed"


class BulkCallItemStatus(BaseModel):
    """Status of one contact in a bulk job."""
    phone_number: str
    contact_name: str
    status: CallStatus
    attempts: int = 0
    error: Optional[str] = None


class BulkCallResponse(BaseModel):
    """Response after dispatching a bulk job."""
    job_id: str
    total_contacts: int
    message: str


class BulkJobStatus(BaseModel):
    """GET /bulk-status/{job_id} response."""
    job_id: str
    total: int
    pending: int
    in_progress: int
    completed: int
    failed: int
    contacts: list[BulkCallItemStatus]


# ───────────────────────────────────────────────────
# Health check
# ───────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    agent: str
    max_call_duration: int
    supabase_connected: bool


# ───────────────────────────────────────────────────
# Lead generation schemas
# ───────────────────────────────────────────────────

class LeadOut(BaseModel):
    """Serialized lead for API responses."""
    id: str
    name: str
    phone: str
    budget: str
    location: str
    property_type: str
    timeline: str
    loan_required: str
    decision_maker: str
    lead_score: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedLeads(BaseModel):
    """Paginated list of leads."""
    total: int
    page: int
    page_size: int
    data: list[LeadOut]


# ───────────────────────────────────────────────────
# Generic API response wrapper
# ───────────────────────────────────────────────────

class APIError(BaseModel):
    """Standard error response body."""
    detail: str
    error_code: Optional[str] = None
