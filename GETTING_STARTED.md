# 🚀 Getting Started — Horizon Realty Voice Agent

> Complete step-by-step guide to set up and run both the **Backend (Python)** and **Frontend (Next.js)** from scratch.

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Project Overview](#2-project-overview)
3. [Folder Structure](#3-folder-structure)
4. [Backend Setup](#4-backend-setup)
   - [4.1 Install Python Dependencies](#41-install-python-dependencies)
   - [4.2 Set Up External Services](#42-set-up-external-services)
   - [4.3 Configure Environment Variables](#43-configure-environment-variables)
   - [4.4 Set Up Supabase Database](#44-set-up-supabase-database)
   - [4.5 Apply Sarvam TTS Patch](#45-apply-sarvam-tts-patch)
   - [4.6 Run the Backend](#46-run-the-backend)
   - [4.7 Verify Backend is Running](#47-verify-backend-is-running)
5. [Frontend Setup](#5-frontend-setup)
   - [5.1 Install Node Dependencies](#51-install-node-dependencies)
   - [5.2 Configure API URL](#52-configure-api-url)
   - [5.3 Run the Frontend](#53-run-the-frontend)
   - [5.4 Verify Frontend is Running](#54-verify-frontend-is-running)
6. [Running Both Together](#6-running-both-together)
7. [Making Your First Call](#7-making-your-first-call)
8. [Using the Dashboard](#8-using-the-dashboard)
9. [API Endpoints Reference](#9-api-endpoints-reference)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. System Requirements

| Requirement | Version |
|-------------|---------|
| **Python** | 3.11 or higher |
| **Node.js** | 18 or higher |
| **npm** | 9 or higher |
| **OS** | Windows 10/11, macOS, or Linux |

Check your versions:

```bash
python --version    # Should show 3.11+
node --version      # Should show v18+
npm --version       # Should show 9+
```

---

## 2. Project Overview

This project has **two parts** that run simultaneously:

| Component | Tech Stack | Default Port | Purpose |
|-----------|-----------|-------------|---------|
| **Backend** | Python, FastAPI, LiveKit Agents | `8081` | Voice agent + REST API |
| **Frontend** | Next.js, React, TypeScript, Tailwind | `3000` | Dashboard UI |

```
┌─────────────────┐         ┌──────────────────┐
│   Frontend       │  HTTP   │    Backend        │
│   Next.js        │────────►│    FastAPI         │
│   localhost:3000  │  :8081  │    + LiveKit Agent │
└─────────────────┘         └──────────────────┘
         │                           │
         │                    ┌──────┴──────┐
         │                    │  Supabase   │
         │                    │  (Database) │
         └────────────────────┴─────────────┘
```

---

## 3. Folder Structure

```
main/                          ← Project root
│
├── app/                       ← Backend (Python)
│   ├── main.py                # Entry point
│   ├── config.py              # Environment configuration
│   ├── api/routes.py          # REST API endpoints
│   ├── services/
│   │   ├── agent_service.py   # Voice agent logic
│   │   ├── call_service.py    # Call dispatch
│   │   └── bulk_service.py    # Bulk calling engine
│   ├── db/
│   │   ├── supabase_client.py # Database client
│   │   └── call_logs.py       # Database operations
│   ├── models/schemas.py      # Data models
│   └── utils/logger.py        # Logging
│
├── worker/
│   └── agent_worker.py        # LiveKit worker entrypoint
│
├── frontend/                  ← Frontend (Next.js)
│   ├── src/
│   │   ├── app/               # Pages (dashboard, make-call, logs, bulk-call)
│   │   ├── components/        # UI components
│   │   ├── lib/api.ts         # API client
│   │   └── types/index.ts     # TypeScript types
│   ├── package.json
│   └── next.config.ts
│
├── .env.local                 # Environment variables (secrets)
├── requirements.txt           # Python dependencies
├── supabase_migration.sql     # Database schema
└── README.md                  # Project documentation
```

---

## 4. Backend Setup

### 4.1 Install Python Dependencies

Open a terminal in the project root (`main/` folder):

```bash
# Create a virtual environment (first time only)
python -m venv venv

# Activate it
# Windows (Command Prompt):
venv\Scripts\activate
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

> ⚠️ You should see `(venv)` in your terminal prompt after activation. Always activate before running the backend.

### 4.2 Set Up External Services

You need accounts on 5 external services. Create them in this order:

#### Step 1: LiveKit Cloud

1. Go to [cloud.livekit.io](https://cloud.livekit.io) → Create account
2. Create a new project
3. Go to **Project Settings → Keys**
4. Copy: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`

#### Step 2: Twilio (Phone Calling)

1. Go to [twilio.com](https://www.twilio.com) → Create account
2. **Buy a phone number** (Phone Numbers → Buy a Number)
3. **Create an Elastic SIP Trunk**:
   - Go to **Elastic SIP Trunking → Trunks → Create**
   - Under **Termination**, add a Termination URI
   - Set up Credential Lists (username + password)
   - Note the **Termination SIP URI**
4. **Create a LiveKit SIP Trunk**:
   - In LiveKit Dashboard → **Telephony → SIP Trunks → Create → Outbound**
   - Enter your Twilio termination SIP URI and credentials
   - Copy the **Trunk ID** (e.g., `ST_xxxxxxxxxxxx`)

#### Step 3: Sarvam AI (Voice)

1. Go to [sarvam.ai](https://sarvam.ai) → Create account
2. Go to Dashboard → API Keys
3. Copy your API key

#### Step 4: Groq (AI Brain)

1. Go to [console.groq.com](https://console.groq.com) → Create account
2. Go to API Keys → Create new key
3. Copy your API key

#### Step 5: Supabase (Database)

1. Go to [supabase.com](https://supabase.com) → Create account
2. Create a new project (choose a region close to you)
3. Wait for the project to finish provisioning
4. Go to **Project Settings → API**
5. Copy: **Project URL** and **anon/public key** (or service_role key)

### 4.3 Configure Environment Variables

Open `.env.local` in the project root and fill in your credentials:

```env
# ── LiveKit Cloud ──
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxx
LIVEKIT_API_SECRET=your-livekit-api-secret

# ── SIP / Twilio ──
SIP_OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxx

# ── Sarvam AI ──
SARVAM_API_KEY=sk_your_sarvam_key

# ── Groq ──
GROQ_API_KEY=gsk_your_groq_key

# ── Supabase ──
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=eyJhbGciOi...your-supabase-key

# ── Settings (optional, these have defaults) ──
MAX_CALL_DURATION_SECONDS=600
API_PORT=8081
```

> 🔒 **NEVER commit `.env.local` to Git.** It contains your secrets.

### 4.4 Set Up Supabase Database

1. Open your Supabase project → **SQL Editor** → **New Query**
2. Copy and paste the contents of `supabase_migration.sql` (from the project root)
3. Click **Run**

This creates the `call_logs` table with the correct schema:

```
┌─────────────────────────────────────────────────────┐
│ call_logs                                           │
├──────────────────┬──────────────┬───────────────────┤
│ id               │ UUID         │ Primary Key       │
│ caller_number    │ TEXT         │ Phone number      │
│ duration_seconds │ FLOAT8       │ Call length       │
│ transcript       │ TEXT         │ Full conversation │
│ created_at       │ TIMESTAMPTZ  │ When it happened  │
└──────────────────┴──────────────┴───────────────────┘
```

### 4.5 Apply Sarvam TTS Patch

> ⚠️ **One-time fix required.** There's a known issue in the Sarvam TTS plugin.

Find this file in your virtual environment:

```
venv/Lib/site-packages/livekit/plugins/sarvam/tts.py
```

Search for `mime_type="audio/wav"` and change it to:

```python
mime_type="audio/mp3"
```

### 4.6 Run the Backend

Make sure your virtual environment is activated, then:

```bash
python -m app.main dev
```

You should see output like:

```
2026-04-05 23:01:32 | INFO | app.main | 🌐 FastAPI server started on 0.0.0.0:8081
2026-04-05 23:01:33 | INFO | livekit.agents | Worker registered with LiveKit Cloud
```

> The backend starts **two things** simultaneously:
> - **FastAPI API Server** on port `8081` (for HTTP requests)
> - **LiveKit Agent Worker** (for handling voice calls)

### 4.7 Verify Backend is Running

Open a new terminal and run:

```bash
# Health check
curl http://localhost:8081/health
```

Expected response:
```json
{
  "status": "healthy",
  "agent": "real-estate-agent",
  "max_call_duration": 600,
  "supabase_connected": true
}
```

On Windows PowerShell, use:
```powershell
Invoke-RestMethod -Uri "http://localhost:8081/health"
```

> ✅ If you see `"status": "healthy"`, the backend is working.
> ⚠️ If `supabase_connected` is `false`, check your `SUPABASE_URL` and `SUPABASE_KEY` in `.env.local`.

---

## 5. Frontend Setup

### 5.1 Install Node Dependencies

Open a **new terminal** (keep the backend running in the first one):

```bash
cd frontend
npm install
```

This installs Next.js, React, Tailwind CSS, shadcn/ui, and all other dependencies.

### 5.2 Configure API URL (Optional)

By default, the frontend connects to `http://localhost:8081` (your backend).

If your backend runs on a different URL or port, create a file `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8081
```

> For most local development, you don't need to change anything — the default works.

### 5.3 Run the Frontend

```bash
npm run dev
```

You should see:

```
▲ Next.js 16.x (Turbopack)
- Local:    http://localhost:3000
- Network:  http://192.168.x.x:3000
✓ Ready in 600ms
```

### 5.4 Verify Frontend is Running

Open your browser and go to:

```
http://localhost:3000
```

You'll be redirected to the **Dashboard** page. You should see:
- A **sidebar** with navigation (Dashboard, Make Call, Bulk Call, Call Logs)
- **4 stat cards** (Total Calls, Calls Answered, Calls Failed, Avg Duration)
- A **Recent Calls** section

> ✅ If you see the dashboard, the frontend is working!
> ⚠️ If stat cards show errors, make sure the backend is running on port 8081.

---

## 6. Running Both Together

You need **two terminal windows** running simultaneously:

### Terminal 1 — Backend

```bash
cd main
.\venv\Scripts\Activate.ps1     # or: source venv/bin/activate
python -m app.main dev
```

### Terminal 2 — Frontend

```bash
cd main/frontend
npm run dev
```

### Quick Reference

| What | Command | URL |
|------|---------|-----|
| Backend API | `python -m app.main dev` | http://localhost:8081 |
| Frontend UI | `npm run dev` (in `frontend/`) | http://localhost:3000 |
| Health check | `curl http://localhost:8081/health` | — |
| API Docs | Open browser | http://localhost:8081/docs |

### Stopping

- **Backend**: Press `Ctrl+C` in Terminal 1
- **Frontend**: Press `Ctrl+C` in Terminal 2

---

## 7. Making Your First Call

### Option A: Using the Dashboard UI (Recommended)

1. Open http://localhost:3000/make-call
2. Enter a **phone number** (with country code, e.g., `+919876543210`)
3. Enter the **contact name** (e.g., `Rahul Sharma`)
4. Click **"Dispatch Call"**
5. You'll see a success toast notification
6. The agent will dial the number within a few seconds

### Option B: Using cURL

```bash
curl -X POST http://localhost:8081/make-call \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+919876543210",
    "contact_name": "Rahul Sharma"
  }'
```

### Option C: Using PowerShell

```powershell
$body = @{
    phone_number = "+919876543210"
    contact_name = "Rahul Sharma"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8081/make-call" -Method POST -Body $body -ContentType "application/json"
```

### Option D: Using Python

```python
import requests

response = requests.post("http://localhost:8081/make-call", json={
    "phone_number": "+919876543210",
    "contact_name": "Rahul Sharma"
})
print(response.json())
```

### What Happens After Dispatching

1. LiveKit creates a new voice room
2. The agent worker picks up the job
3. Agent dials the number via Twilio SIP
4. When the caller picks up → agent greets them by name
5. Agent qualifies them (Budget, Authority, Need, Timeline)
6. After the call ends → transcript + duration are logged to Supabase
7. You can see the call log in the Dashboard or Call Logs page

---

## 8. Using the Dashboard

### Dashboard Page (`/dashboard`)

- **4 stat cards**: Total Calls, Answered, Failed, Average Duration
- **Recent Calls list**: Latest 5 calls with status badges
- **Auto-refreshes** every 10 seconds

### Make Call Page (`/make-call`)

- Enter phone number + name
- Click dispatch
- See loading → success states
- Info panel explains the call flow

### Bulk Call Page (`/bulk-call`)

- Add multiple contacts (phone + name)
- Click "Dispatch N Calls"
- Watch real-time progress:
  - `pending` → `in-progress` → `completed` / `failed`
- Calls run in parallel (5 at a time by default)
- Failed calls auto-retry (up to 3 times)

### Call Logs Page (`/logs`)

- **Search** by phone number or transcript
- **Pagination** (10 per page)
- **View transcript**: Click the eye icon to expand
- **Copy phone number**: Click the copy icon
- **Export CSV**: Download all logs as a spreadsheet

---

## 9. API Endpoints Reference

All endpoints are on the backend (`http://localhost:8081`):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/make-call` | Dispatch a single call |
| `POST` | `/bulk-call` | Dispatch calls to multiple contacts |
| `GET` | `/bulk-status/{job_id}` | Check bulk job progress |
| `GET` | `/calls` | Paginated call logs |
| `GET` | `/calls/{id}` | Single call log by UUID |

### Example: Bulk Call

```bash
curl -X POST http://localhost:8081/bulk-call \
  -H "Content-Type: application/json" \
  -d '{
    "contacts": [
      {"phone_number": "+919876543210", "contact_name": "Rahul"},
      {"phone_number": "+919876543211", "contact_name": "Priya"},
      {"phone_number": "+919876543212", "contact_name": "Amit"}
    ]
  }'
```

Response:
```json
{
  "job_id": "a1b2c3d4-...",
  "total_contacts": 3,
  "message": "Bulk job created. 3 calls queued."
}
```

Check progress:
```bash
curl http://localhost:8081/bulk-status/a1b2c3d4-...
```

### Example: Get Call Logs

```bash
# Page 1, 10 per page
curl "http://localhost:8081/calls?page=1&page_size=10"
```

---

## 10. Troubleshooting

### Backend won't start

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError` | Make sure venv is activated: `.\venv\Scripts\Activate.ps1` |
| `ValidationError` for settings | Check all required values in `.env.local` are filled |
| `LIVEKIT_URL not set` | Add your LiveKit Cloud URL to `.env.local` |
| Port 8081 already in use | Change `API_PORT` in `.env.local` or kill the process using port 8081 |

### Frontend won't start

| Problem | Solution |
|---------|----------|
| `npm: command not found` | Install Node.js from [nodejs.org](https://nodejs.org) |
| Port 3000 already in use | Stop other dev servers, or `npx next dev -p 3001` |
| Dependency errors | Delete `node_modules/` and `package-lock.json`, then `npm install` |

### Dashboard shows errors / empty

| Problem | Solution |
|---------|----------|
| "Unable to load dashboard" | Backend is not running — start it with `python -m app.main dev` |
| "Failed to fetch" in console | Backend is on wrong port — check `NEXT_PUBLIC_API_URL` |
| CORS errors in browser | Backend already has CORS configured — make sure you're using the new `app/main.py` |
| `supabase_connected: false` | Fill in `SUPABASE_URL` and `SUPABASE_KEY` in `.env.local` |

### Calls don't connect

| Problem | Solution |
|---------|----------|
| SIP call failed | Check `SIP_OUTBOUND_TRUNK_ID` is correct in `.env.local` |
| "Number busy" / "No answer" | The person didn't pick up — try again |
| LiveKit error | Verify `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` |
| No audio / silent call | Apply the Sarvam TTS patch (Section 4.5) |

### Common Commands Cheat Sheet

```bash
# ── Backend ──
.\venv\Scripts\Activate.ps1          # Activate virtualenv (Windows)
python -m app.main dev               # Start backend
curl http://localhost:8081/health     # Health check

# ── Frontend ──
cd frontend
npm install                          # Install deps (first time)
npm run dev                          # Start dev server
npm run build                        # Production build

# ── Both together (2 terminals) ──
# Terminal 1: python -m app.main dev
# Terminal 2: cd frontend && npm run dev

# ── Testing a call ──
curl -X POST http://localhost:8081/make-call \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+91XXXXXXXXXX", "contact_name": "Test"}'
```

---

## ✅ Pre-Flight Checklist

Before your first call, verify:

- [ ] Python 3.11+ installed
- [ ] Node.js 18+ installed
- [ ] Virtual environment created and activated
- [ ] `pip install -r requirements.txt` completed
- [ ] LiveKit Cloud account set up, keys copied
- [ ] Twilio SIP trunk created, linked to LiveKit
- [ ] Sarvam AI API key copied
- [ ] Groq API key copied
- [ ] Supabase project created
- [ ] `supabase_migration.sql` executed in Supabase SQL Editor
- [ ] `.env.local` filled with ALL required values
- [ ] Sarvam TTS patch applied (audio/wav → audio/mp3)
- [ ] Backend starts: `python -m app.main dev` → no errors
- [ ] Health check passes: `curl http://localhost:8081/health`
- [ ] Frontend starts: `cd frontend && npm run dev` → no errors
- [ ] Dashboard loads: http://localhost:3000 shows the UI
- [ ] Test call works from the Make Call page

---

*Built with ❤️ by Horizon Realty Engineering*
