# 🏠 Horizon Realty — AI Voice Agent

> **An intelligent outbound voice agent that qualifies real estate buyers through natural phone conversations.**
> Built with **LiveKit Agents**, **Sarvam AI** (STT/TTS), **Groq LLM**, **Twilio SIP**, and **Supabase**.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![LiveKit](https://img.shields.io/badge/LiveKit-Agents_1.4-purple.svg)](https://docs.livekit.io/agents)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup Guide](#setup-guide)
  - [1. Clone & Install](#1-clone--install)
  - [2. Twilio + LiveKit SIP Setup](#2-twilio--livekit-sip-setup)
  - [3. Supabase Setup](#3-supabase-setup)
  - [4. Configure Environment Variables](#4-configure-environment-variables)
  - [5. Run the Agent](#5-run-the-agent)
- [API Reference](#api-reference)
  - [Make a Single Call](#post-make-call)
  - [Bulk Call Multiple Contacts](#post-bulk-call)
  - [Check Bulk Job Status](#get-bulk-statusjob_id)
  - [Fetch Call Logs](#get-calls)
  - [Fetch a Single Call Log](#get-callsid)
  - [Health Check](#get-health)
- [Bulk Calling System](#bulk-calling-system)
- [VAD Tuning Guide](#vad-tuning-guide)
- [Cost Protection](#cost-protection)
- [Environment Variables Reference](#environment-variables-reference)
- [Pre-Flight Checklist](#pre-flight-checklist)
- [Important Patch](#important-patch)
- [License](#license)

---

## Overview

This is a **production-grade outbound AI voice agent** designed for real estate lead qualification. When triggered via API, the agent:

1. **Calls** the prospect using Twilio SIP through LiveKit
2. **Greets** them by name with a warm, human-like voice
3. **Qualifies** them using the BANT framework (Budget, Authority, Need, Timeline)
4. **Classifies** them as HOT, WARM, or COLD leads
5. **Logs** the full call transcript and metadata to Supabase

The entire pipeline is **streaming end-to-end** — the caller hears the agent start responding within ~1 second.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Caller     │◄───►│  Twilio SIP  │◄───►│ LiveKit Cloud│◄───►│  Voice Agent     │
│  (Phone)     │     │   Trunk      │     │   (Room)     │     │  (Python)        │
└─────────────┘     └──────────────┘     └──────────────┘     └────────┬─────────┘
                                                                       │
                                              ┌────────────────────────┼────────────────────────┐
                                              │                        │                        │
                                         ┌────▼─────┐          ┌──────▼────┐          ┌────────▼───┐
                                         │ Sarvam   │          │  Groq     │          │  Sarvam    │
                                         │ STT      │─────────►│  LLM      │─────────►│  TTS       │
                                         │(saaras)  │ stream   │(llama 3.3)│  stream  │ (bulbul)   │
                                         └──────────┘          └───────────┘          └────────────┘
                                                                                            │
                            ┌──────────────┐                                         ┌──────▼──────┐
                            │  FastAPI     │                                         │  Supabase   │
                            │  REST API    │                                         │  call_logs  │
                            │  (Port 8081) │                                         │ (PostgreSQL)│
                            └──────────────┘                                         └─────────────┘
```

### Streaming Pipeline (Ultra-Low Latency)

The entire pipeline is **streaming** — no stage waits for a complete response:

| Stage | What Happens | Latency |
|-------|-------------|---------|
| 1. Caller speaks | Audio streams to Sarvam STT | Real-time |
| 2. Sarvam STT | Streams partial transcripts as caller speaks | ~100ms |
| 3. Silero VAD | Detects end-of-utterance | ~50ms |
| 4. Groq LLM | Streams response tokens immediately | ~200ms to first token |
| 5. Sarvam TTS | Synthesizes audio from **first tokens**, not full text | Streaming |
| 6. Caller hears | Agent voice starts almost immediately | **< 1s total** |

**Barge-in:** If the caller speaks while the agent is talking, the agent stops immediately and listens.

---

## How It Works

### Call Lifecycle

```
    API Request                    LiveKit                       Phone Call
   ─────────────                  ──────────                    ────────────
   POST /make-call  ──►  Dispatch agent job  ──►  Create LiveKit room
                                                       │
                                                       ▼
                                              Dial via Twilio SIP
                                                       │
                                                       ▼
                                              Caller picks up
                                                       │
                                                       ▼
                                    ┌──── Agent greets by name ◄────┐
                                    │         (proactive)           │
                                    ▼                               │
                              Caller speaks                         │
                                    │                               │
                                    ▼                               │
                            STT transcribes                         │
                                    │                               │
                                    ▼                               │
                          LLM generates reply                       │
                                    │                               │
                                    ▼                               │
                            TTS synthesizes                         │
                                    │                               │
                                    ▼                               │
                           Agent speaks reply ──────────────────────┘
                                    │
                                    ▼  (when done or max duration)
                              Call ends
                                    │
                                    ▼
                    Log to Supabase (transcript + duration)
```

### Agent Conversation Flow

The agent follows a structured qualification flow:

1. **Greeting** — Confirm identity, mention property interest, check if they can talk
2. **Interest Check** — Are they actively looking? If not → politely end
3. **BANT Qualification**:
   - **Budget** → Ask price range
   - **Authority** → Are they the decision maker?
   - **Need** → Property type, location, loan requirement
   - **Timeline** → When planning to buy?
4. **Wrap-up** — Thank them, promise follow-up from a specialist

The agent adapts its tone to the caller (excited, confused, hesitant) and never asks multiple questions at once.

---

## Project Structure

```
main/
│
├── app/
│   ├── __init__.py
│   ├── main.py                     # Entry point — FastAPI app + LiveKit worker startup
│   ├── config.py                   # Pydantic Settings — typed env var management
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py              # All REST API endpoints (thin routing layer)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── agent_service.py       # SYSTEM_PROMPT, RealEstateAgent class, voice pipeline
│   │   ├── call_service.py        # Single call dispatch via LiveKit API
│   │   └── bulk_service.py        # Bulk calling engine (queue + retry + tracking)
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── supabase_client.py     # Lazy singleton Supabase client wrapper
│   │   └── call_logs.py           # CRUD operations for call_logs table
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py             # All Pydantic request/response models
│   │
│   └── utils/
│       ├── __init__.py
│       └── logger.py              # Structured logging factory
│
├── worker/
│   ├── __init__.py
│   └── agent_worker.py            # LiveKit entrypoint — full call lifecycle
│
├── .env.local                     # Environment variables (NEVER commit!)
├── requirements.txt               # Python dependencies
├── supabase_migration.sql         # SQL to create call_logs table
└── README.md                      # This file
```

### Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `app/config.py` | Loads & validates all env vars at startup via Pydantic |
| `app/api/routes.py` | HTTP endpoints — validates input, delegates to services, formats output |
| `app/services/agent_service.py` | Voice agent class, system prompt, VAD + STT + LLM + TTS pipeline |
| `app/services/call_service.py` | Dispatches a single call through LiveKit Agent Dispatch API |
| `app/services/bulk_service.py` | Manages bulk call jobs with concurrency control and retry logic |
| `app/db/supabase_client.py` | Singleton Supabase client with lazy initialization |
| `app/db/call_logs.py` | Insert (with retry + backoff), paginated list, single fetch |
| `app/models/schemas.py` | 15+ Pydantic models for type-safe API boundaries |
| `worker/agent_worker.py` | LiveKit job handler — connect, dial, greet, monitor, log |

---

## Prerequisites

You need accounts with the following services:

| Service | What For | Sign Up |
|---------|----------|---------|
| **LiveKit Cloud** | Voice room infrastructure + agent dispatch | [cloud.livekit.io](https://cloud.livekit.io) |
| **Twilio** | Phone number + Elastic SIP trunk for outbound calls | [twilio.com](https://www.twilio.com) |
| **Sarvam AI** | Speech-to-Text (saaras:v3) + Text-to-Speech (bulbul:v3) | [sarvam.ai](https://sarvam.ai) |
| **Groq** | LLM inference (llama-3.3-70b-versatile) | [console.groq.com](https://console.groq.com) |
| **Supabase** | PostgreSQL database for call logging | [supabase.com](https://supabase.com) |

---

## Setup Guide

### 1. Clone & Install

```bash
git clone <your-repo-url>
cd main

# Create a virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Download the Silero VAD model (one-time)
python -m app.main download-files
```

### 2. Twilio + LiveKit SIP Setup

#### Step 1: Create a Twilio Elastic SIP Trunk

1. Go to [Twilio Console](https://console.twilio.com) → **Elastic SIP Trunking** → **Trunks**
2. Click **Create new SIP Trunk**
3. Under **Termination**, add a Termination URI and set up **Credential Lists**
4. Note down the **Termination SIP URI**, **username**, and **password**

#### Step 2: Create a LiveKit Outbound SIP Trunk

1. Go to [LiveKit Cloud Dashboard](https://cloud.livekit.io) → **Telephony** → **SIP Trunks**
2. Click **Create Trunk** → **Outbound**
3. Enter your Twilio termination SIP URI and credentials
4. Copy the **Trunk ID** (e.g., `ST_xxxxxxxxxxxx`)
5. Set this as `SIP_OUTBOUND_TRUNK_ID` in your `.env.local`

**Or use the LiveKit CLI:**
```bash
lk sip outbound create outbound-trunk.json
```

#### Step 3: Buy a Twilio Phone Number

1. In Twilio Console → **Phone Numbers** → **Buy a Number**
2. Associate it with your SIP Trunk for caller ID

### 3. Supabase Setup

1. Create a project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** → **New Query**
3. Paste and run the contents of `supabase_migration.sql`:

```sql
-- This creates the call_logs table with proper indexes
CREATE TABLE IF NOT EXISTS call_logs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    caller_number    TEXT        NOT NULL,
    duration_seconds FLOAT8      NOT NULL DEFAULT 0,
    transcript       TEXT        NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_call_logs_created_at ON call_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_call_logs_caller_number ON call_logs (caller_number);
```

4. Go to **Project Settings** → **API** and copy:
   - **Project URL** → `SUPABASE_URL`
   - **anon/public key** (or service_role key) → `SUPABASE_KEY`

### 4. Configure Environment Variables

```bash
# Edit .env.local and fill in all values
```

Key variables to set:

| Variable | Example |
|----------|---------|
| `LIVEKIT_URL` | `wss://myproject.livekit.cloud` |
| `LIVEKIT_API_KEY` | `APIxxxxxxxx` |
| `LIVEKIT_API_SECRET` | `your-secret-here` |
| `SIP_OUTBOUND_TRUNK_ID` | `ST_xxxxxxxxxxxx` |
| `SARVAM_API_KEY` | `sk_xxxxx` |
| `GROQ_API_KEY` | `gsk_xxxxx` |
| `SUPABASE_URL` | `https://xyzcompany.supabase.co` |
| `SUPABASE_KEY` | `eyJhbGciOi...` |

See [Environment Variables Reference](#environment-variables-reference) for all options.

### 5. Run the Agent

```bash
python -m app.main dev
```

This starts **two processes simultaneously**:

| Process | Role | Runs On |
|---------|------|---------|
| **FastAPI Server** | HTTP API for triggering calls | `http://localhost:8081` (background thread) |
| **LiveKit Agent Worker** | Connects to LiveKit Cloud, handles call jobs | Main process |

You'll see output like:
```
2026-04-05 22:46:41 | INFO | app.main | 🌐 FastAPI server started on 0.0.0.0:8081
2026-04-05 22:46:42 | INFO | livekit.agents | Worker registered with LiveKit Cloud
```

---

## API Reference

All responses are structured JSON. Errors return `{"detail": "error message"}`.

### `POST /make-call`

**Dispatch a single outbound qualification call.**

**Request:**
```bash
curl -X POST http://localhost:8081/make-call \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+919876543210",
    "contact_name": "Rahul Sharma"
  }'
```

**Response (200):**
```json
{
  "status": "dispatched",
  "phone_number": "+919876543210",
  "contact_name": "Rahul Sharma",
  "message": "Call has been dispatched. The agent will dial the number shortly."
}
```

**What happens next:**
1. LiveKit creates a new room
2. The agent worker picks up the job
3. Agent dials the number via Twilio SIP
4. When the caller picks up, the agent greets them by name
5. After the call ends, transcript + duration are logged to Supabase

---

### `POST /bulk-call`

**Dispatch calls to multiple contacts at once.**

Calls are processed in parallel (default: 5 concurrent calls) with automatic retry on failure.

**Request:**
```bash
curl -X POST http://localhost:8081/bulk-call \
  -H "Content-Type: application/json" \
  -d '{
    "contacts": [
      {"phone_number": "+919876543210", "contact_name": "Rahul Sharma"},
      {"phone_number": "+919876543211", "contact_name": "Priya Patel"},
      {"phone_number": "+919876543212", "contact_name": "Amit Kumar"},
      {"phone_number": "+919876543213", "contact_name": "Sneha Gupta"},
      {"phone_number": "+919876543214", "contact_name": "Vikram Singh"}
    ]
  }'
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "total_contacts": 5,
  "message": "Bulk job created. 5 calls queued."
}
```

---

### `GET /bulk-status/{job_id}`

**Check the progress of a bulk calling job.**

**Request:**
```bash
curl http://localhost:8081/bulk-status/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "total": 5,
  "pending": 1,
  "in_progress": 2,
  "completed": 2,
  "failed": 0,
  "contacts": [
    {
      "phone_number": "+919876543210",
      "contact_name": "Rahul Sharma",
      "status": "completed",
      "attempts": 1,
      "error": null
    },
    {
      "phone_number": "+919876543211",
      "contact_name": "Priya Patel",
      "status": "completed",
      "attempts": 1,
      "error": null
    },
    {
      "phone_number": "+919876543212",
      "contact_name": "Amit Kumar",
      "status": "in-progress",
      "attempts": 1,
      "error": null
    },
    {
      "phone_number": "+919876543213",
      "contact_name": "Sneha Gupta",
      "status": "in-progress",
      "attempts": 1,
      "error": null
    },
    {
      "phone_number": "+919876543214",
      "contact_name": "Vikram Singh",
      "status": "pending",
      "attempts": 0,
      "error": null
    }
  ]
}
```

**Status values:** `pending` → `in-progress` → `completed` or `failed`

---

### `GET /calls`

**Fetch paginated call logs (newest first).**

**Request:**
```bash
# Default: page 1, 20 results per page
curl http://localhost:8081/calls

# Custom pagination
curl "http://localhost:8081/calls?page=2&page_size=10"
```

**Response (200):**
```json
{
  "total": 47,
  "page": 1,
  "page_size": 20,
  "data": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "caller_number": "+919876543210",
      "duration_seconds": 145.3,
      "transcript": "Agent (Anand): Hi Rahul, this is Anand from Horizon Realty...\nCaller: Yes, hi Anand...",
      "created_at": "2026-04-05T17:30:00Z"
    }
  ]
}
```

**Query Parameters:**

| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `page` | int | 1 | ≥ 1 | Page number |
| `page_size` | int | 20 | 1–100 | Results per page |

---

### `GET /calls/{id}`

**Fetch a single call log by UUID.**

**Request:**
```bash
curl http://localhost:8081/calls/550e8400-e29b-41d4-a716-446655440000
```

**Response (200):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "caller_number": "+919876543210",
  "duration_seconds": 145.3,
  "transcript": "Agent (Anand): Hi Rahul, this is Anand from Horizon Realty...\nCaller: Yes, hi Anand...",
  "created_at": "2026-04-05T17:30:00Z"
}
```

**Response (404):**
```json
{
  "detail": "Call 550e8400-e29b-41d4-a716-446655440000 not found"
}
```

---

### `GET /health`

**Health check — verify the API is running and dependencies are reachable.**

**Request:**
```bash
curl http://localhost:8081/health
```

**Response (200):**
```json
{
  "status": "healthy",
  "agent": "real-estate-agent",
  "max_call_duration": 600,
  "supabase_connected": true
}
```

---

## Bulk Calling System

The bulk calling system is designed for calling large contact lists efficiently.

### How It Works

1. **Submit a job** via `POST /bulk-call` with a list of contacts
2. The system returns a `job_id` immediately (non-blocking)
3. Calls are processed in the background with:
   - **Concurrency limit** — default 5 parallel calls (configurable via `BULK_MAX_CONCURRENCY`)
   - **Automatic retry** — failed calls are retried up to 3 times with exponential backoff
   - **Per-contact tracking** — each contact has its own status and error field
4. **Poll for progress** via `GET /bulk-status/{job_id}`

### Retry Logic

| Attempt | Delay Before Retry |
|---------|-------------------|
| 1st attempt | Immediate |
| 2nd attempt | 2 seconds |
| 3rd attempt | 4 seconds |

After 3 failures, the contact is marked as `failed` with the last error message.

### Configuration

| Env Variable | Default | Description |
|-------------|---------|-------------|
| `BULK_MAX_CONCURRENCY` | 5 | Maximum parallel calls |
| `BULK_RETRY_MAX_ATTEMPTS` | 3 | Max retry attempts per contact |
| `BULK_RETRY_BASE_DELAY` | 2.0 | Base delay in seconds (doubled each retry) |

---

## VAD Tuning Guide

The Voice Activity Detection (VAD) parameters in `app/services/agent_service.py` control how the agent detects when the caller is speaking vs. silent.

```python
silero.VAD.load(
    min_speech_duration=0.06,     # Min audio duration to count as "speech"
    min_silence_duration=0.45,    # Wait time after speech stops before responding
    prefix_padding_duration=0.3,  # Audio padding before detected speech
    activation_threshold=0.45,    # Probability threshold for speech detection
)
```

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| Agent triggers on background noise | ↑ Increase `min_speech_duration` to `0.15` |
| Agent cuts caller off mid-sentence | ↑ Increase `min_silence_duration` to `0.7` |
| First syllable of words gets clipped | ↑ Increase `prefix_padding_duration` to `0.6` |
| Agent doesn't hear quiet speakers | ↓ Decrease `activation_threshold` to `0.35` |
| Agent keeps listening to silence | ↑ Increase `activation_threshold` to `0.6` |

---

## Cost Protection

The agent includes a configurable maximum call duration (`MAX_CALL_DURATION_SECONDS`, default: **10 minutes**).

When a call reaches this limit:

1. ⏰ The agent politely tells the caller it needs to wrap up
2. 🤝 Promises a team member from Horizon Realty will follow up
3. 📴 Hangs up the call gracefully

This prevents stuck or looping calls from racking up API costs from Twilio, Sarvam, and Groq.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LIVEKIT_URL` | ✅ | — | LiveKit Cloud WebSocket URL |
| `LIVEKIT_API_KEY` | ✅ | — | API key from LiveKit Cloud |
| `LIVEKIT_API_SECRET` | ✅ | — | API secret from LiveKit Cloud |
| `SIP_OUTBOUND_TRUNK_ID` | ✅ | — | LiveKit SIP trunk ID linked to Twilio |
| `SARVAM_API_KEY` | ✅ | — | Sarvam AI API key |
| `GROQ_API_KEY` | ✅ | — | Groq API key |
| `SUPABASE_URL` | ⚠️ | `""` | Supabase project URL (needed for logging) |
| `SUPABASE_KEY` | ⚠️ | `""` | Supabase anon or service_role key |
| `MAX_CALL_DURATION_SECONDS` | ❌ | `600` | Max call length before auto-hangup |
| `API_PORT` | ❌ | `8081` | FastAPI server port |
| `API_HOST` | ❌ | `0.0.0.0` | FastAPI server bind address |
| `BULK_MAX_CONCURRENCY` | ❌ | `5` | Max parallel calls in bulk mode |
| `BULK_RETRY_MAX_ATTEMPTS` | ❌ | `3` | Retry attempts per failed call |
| `BULK_RETRY_BASE_DELAY` | ❌ | `2.0` | Base delay for exponential backoff (seconds) |
| `LOG_LEVEL` | ❌ | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR) |

> **Note:** The agent runs fine without Supabase (⚠️) — it just won't persist call logs. All other ✅ variables are required for calls to work.

---

## Pre-Flight Checklist

Before your first call, verify everything is set up:

- [ ] **LiveKit Cloud** account created and project set up
- [ ] **LiveKit API Key + Secret** obtained from project settings
- [ ] **Twilio** account created with an Elastic SIP Trunk configured
- [ ] **Twilio phone number** purchased and associated with the SIP trunk
- [ ] **LiveKit SIP outbound trunk** created and linked to Twilio
- [ ] **Sarvam AI** account created and API key generated
- [ ] **Groq** account created and API key generated
- [ ] **Supabase** project created and `call_logs` table created via SQL
- [ ] `.env.local` filled with all required values
- [ ] `pip install -r requirements.txt` completed successfully
- [ ] `python -m app.main dev` starts without errors
- [ ] Health check works: `curl http://localhost:8081/health`
- [ ] Test call works: `curl -X POST http://localhost:8081/make-call -H "Content-Type: application/json" -d '{"phone_number": "+91XXXXXXXXXX", "contact_name": "Test"}'`

---

## Important Patch

> ⚠️ **Sarvam TTS Plugin Fix**
>
> In `livekit/plugins/sarvam/tts.py`, change:
> ```python
> mime_type="audio/wav"
> ```
> To:
> ```python
> mime_type="audio/mp3"
> ```
> This fixes audio format compatibility issues with the Sarvam TTS API.

---

## Making Your First Call (Step-by-Step)

### Using cURL (recommended)

```bash
# 1. Verify the agent is running
curl http://localhost:8081/health

# 2. Make a test call
curl -X POST http://localhost:8081/make-call \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+919876543210",
    "contact_name": "Rahul Sharma"
  }'

# 3. Check logs after the call
curl http://localhost:8081/calls
```

### Using PowerShell (Windows)

```powershell
# Health check
Invoke-RestMethod -Uri "http://localhost:8081/health"

# Make a call
$body = @{
    phone_number = "+919876543210"
    contact_name = "Rahul Sharma"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8081/make-call" -Method POST -Body $body -ContentType "application/json"

# Bulk call
$bulk = @{
    contacts = @(
        @{ phone_number = "+919876543210"; contact_name = "Rahul" },
        @{ phone_number = "+919876543211"; contact_name = "Priya" }
    )
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Uri "http://localhost:8081/bulk-call" -Method POST -Body $bulk -ContentType "application/json"
```

### Using Python

```python
import requests

BASE_URL = "http://localhost:8081"

# Single call
response = requests.post(f"{BASE_URL}/make-call", json={
    "phone_number": "+919876543210",
    "contact_name": "Rahul Sharma"
})
print(response.json())

# Bulk call
response = requests.post(f"{BASE_URL}/bulk-call", json={
    "contacts": [
        {"phone_number": "+919876543210", "contact_name": "Rahul"},
        {"phone_number": "+919876543211", "contact_name": "Priya"},
        {"phone_number": "+919876543212", "contact_name": "Amit"},
    ]
})
job = response.json()
print(f"Job ID: {job['job_id']}")

# Check bulk job status
status = requests.get(f"{BASE_URL}/bulk-status/{job['job_id']}")
print(status.json())

# Get call logs
logs = requests.get(f"{BASE_URL}/calls", params={"page": 1, "page_size": 10})
print(logs.json())
```

### Using LiveKit CLI

```bash
lk dispatch create \
  --new-room \
  --agent-name real-estate-agent \
  --metadata '{"phone_number": "+919876543210", "contact_name": "Rahul Sharma"}'
```

---

## License

Private — Horizon Realty
