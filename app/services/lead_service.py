"""
Lead extraction service.

Uses the Groq LLM to analyze call transcripts and extract
structured lead data with BANT qualification scoring.
"""

from __future__ import annotations

import json
import asyncio
from typing import Optional

from groq import Groq

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

LEAD_EXTRACTION_PROMPT = """You are a lead qualification analyst for a real estate company.

Analyze the following phone call transcript between an AI agent (Anand from Horizon Realty) and a potential property buyer.

Extract the following information from the conversation. If a piece of information was NOT discussed or is unclear, use "unknown".

You MUST respond with ONLY a valid JSON object — no markdown, no explanation, no extra text.

JSON schema:
{{
  "name": "string — caller's name",
  "phone": "string — caller's phone number",
  "budget": "string — budget range mentioned (e.g. '50-80 lakhs', '1-2 crores')",
  "location": "string — preferred location or area",
  "property_type": "string — flat, villa, plot, commercial, etc.",
  "timeline": "string — when they plan to buy (e.g. '3 months', 'immediately', '1 year')",
  "loan_required": "string — yes, no, or unknown",
  "decision_maker": "string — yes, no, or unknown (whether they are the decision maker)",
  "lead_score": "string — HOT, WARM, or COLD"
}}

LEAD SCORING RULES:
- HOT: Actively looking, has budget, decision maker, buying within 3 months
- WARM: Interested but browsing, some details shared, timeline 3-12 months
- COLD: Not interested, refused to talk, no details shared, no clear timeline

IMPORTANT:
- Do NOT hallucinate — only extract what is actually in the transcript
- If the call was very short or the person didn't engage, score as COLD
- Output ONLY the JSON object, nothing else

TRANSCRIPT:
{transcript}
"""


async def extract_lead_from_transcript(
    transcript: str,
    phone_number: str,
    contact_name: str = "",
) -> Optional[dict]:
    """
    Analyze a call transcript using Groq LLM and extract structured lead data.

    Returns a dict matching the lead schema, or None on failure.
    Error-isolated: never crashes the calling code.
    """
    if not transcript or transcript == "(no transcript captured)":
        logger.warning("⚠️  No transcript to analyze for %s", phone_number)
        return None

    try:
        # Run synchronous Groq client in executor to avoid blocking
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _call_groq(transcript),
        )

        if result is None:
            return None

        # Inject phone number and name (more reliable than LLM extraction)
        result["phone"] = phone_number
        if contact_name and result.get("name", "unknown") == "unknown":
            result["name"] = contact_name

        # Validate lead_score
        if result.get("lead_score") not in ("HOT", "WARM", "COLD"):
            result["lead_score"] = "COLD"

        logger.info(
            "🎯 Lead extracted for %s — score: %s, budget: %s, location: %s",
            phone_number,
            result.get("lead_score"),
            result.get("budget"),
            result.get("location"),
        )

        return result

    except Exception as e:
        logger.error("❌ Lead extraction failed for %s: %s", phone_number, e)
        return None


def _call_groq(transcript: str) -> Optional[dict]:
    """Synchronous Groq API call (runs in thread executor)."""
    client = Groq(api_key=settings.groq_api_key)

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": "You are a JSON extraction assistant. Output ONLY valid JSON. No markdown, no explanation, no code fences.",
            },
            {
                "role": "user",
                "content": LEAD_EXTRACTION_PROMPT.format(transcript=transcript),
            },
        ],
        temperature=0.1,
        max_tokens=800,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or ""
    raw = raw.strip()

    if not raw:
        logger.error("❌ Groq returned empty response")
        return None

    # Robust JSON extraction: try multiple strategies
    data = _extract_json(raw)

    if data is None:
        logger.error("❌ Could not extract valid JSON from LLM response: %s", raw[:300])
        return None

    # Ensure all expected fields exist
    expected_fields = [
        "name", "phone", "budget", "location", "property_type",
        "timeline", "loan_required", "decision_maker", "lead_score",
    ]
    for field in expected_fields:
        if field not in data:
            data[field] = "unknown"

    return data


def _extract_json(raw: str) -> Optional[dict]:
    """
    Try multiple strategies to extract a JSON object from a string.
    Handles: raw JSON, markdown fences, extra text before/after.
    """
    import re

    # Strategy 1: Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Strip markdown code fences (```json ... ``` or ``` ... ```)
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find the first { ... } block
    brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None
