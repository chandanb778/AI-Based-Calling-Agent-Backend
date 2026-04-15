# 🚀 Deployment Guide — Horizon Realty Voice Agent

This project has **two deployable parts**:

| Component | Tech | Best Hosting | Why |
|-----------|------|-------------|-----|
| **Backend** | Python (FastAPI + LiveKit Worker) | **Railway** | Persistent WebSocket connections, Docker support, easy env vars |
| **Frontend** | Next.js | **Vercel** | Zero-config Next.js hosting, global CDN, free tier |

> **Database** (Supabase) is already hosted — no deployment needed.

---

## Architecture Overview

```
                 ┌─────────────────────┐
    Users ──────►│  Vercel (Frontend)   │
                 │  Next.js Dashboard   │
                 └────────┬────────────┘
                          │ API calls
                          ▼
                 ┌─────────────────────┐
                 │  Railway (Backend)   │
                 │  FastAPI :8081       │◄────► Supabase (DB)
                 │  LiveKit Worker      │◄────► LiveKit Cloud
                 └────────┬────────────┘
                          │ SIP
                          ▼
                 ┌─────────────────────┐
                 │  Twilio (Phone)      │
                 └─────────────────────┘
```

---

## Part 1: Deploy Backend to Railway

### Step 1: Create Railway Project

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select your `RealEstateVoiceAgent` repository
4. Railway will auto-detect the `Dockerfile`

### Step 2: Configure Environment Variables

In Railway dashboard → your service → **Variables** tab, add ALL of these:

```env
# LiveKit
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret

# SIP / Twilio
SIP_OUTBOUND_TRUNK_ID=your_trunk_id

# Sarvam AI
SARVAM_API_KEY=your_sarvam_key

# Groq LLM
GROQ_API_KEY=your_groq_key

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key

# Server config
API_PORT=8081
API_HOST=0.0.0.0
```

### Step 3: Configure Networking

1. In Railway → your service → **Settings** → **Networking**
2. Click **"Generate Domain"** to get a public URL (e.g., `your-app.up.railway.app`)
3. Under **Port**, set it to `8081`

### Step 4: Deploy

Railway auto-deploys on every `git push` to `main`. You can also manually trigger a deploy from the dashboard.

**Verify:** Visit `https://your-app.up.railway.app/health` — you should see:
```json
{"status": "healthy", "agent": "real-estate-agent", ...}
```

### Step 5: Update LiveKit Agent Config

In your [LiveKit Cloud dashboard](https://cloud.livekit.io):
1. Go to **Settings** → **Agents**
2. Update the agent's WebSocket URL to your Railway URL (if needed)

> **Note:** The LiveKit worker connects *outward* to LiveKit Cloud via WebSocket — Railway doesn't need inbound WebSocket support.

---

## Part 2: Deploy Frontend to Vercel

### Step 1: Create Vercel Project

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub
2. Click **"Add New..."** → **"Project"**
3. Import your `RealEstateVoiceAgent` repository
4. **IMPORTANT — Set the Root Directory**: In the project configuration, set `Root Directory` to `frontend`

### Step 2: Configure Build Settings

Vercel should auto-detect Next.js. Verify these settings:

| Setting | Value |
|---------|-------|
| Framework Preset | Next.js |
| Root Directory | `frontend` |
| Build Command | `npm run build` |
| Output Directory | `.next` |

### Step 3: Set Environment Variables

In Vercel → your project → **Settings** → **Environment Variables**, add:

```env
NEXT_PUBLIC_API_URL=https://your-app.up.railway.app
```

Replace `your-app.up.railway.app` with your actual Railway domain from Part 1.

### Step 4: Deploy

Click **"Deploy"**. Vercel will build and deploy your frontend.

**Verify:** Visit your Vercel URL — the dashboard should load and connect to your Railway backend.

### Step 5: Custom Domain (Optional)

In Vercel → **Settings** → **Domains**, add your custom domain (e.g., `dashboard.horizonrealty.com`).

---

## Part 3: Update CORS (Important!)

After deployment, update your backend CORS to restrict origins to your Vercel domain.

In `app/main.py`, change:

```python
# BEFORE (development)
allow_origins=["*"],

# AFTER (production) — replace with your actual Vercel URL
allow_origins=[
    "https://your-app.vercel.app",
    "https://dashboard.horizonrealty.com",  # if custom domain
    "http://localhost:3000",                 # keep for local dev
],
```

---

## Part 4: Database Migrations

Make sure your Supabase has the required tables. Run these in **Supabase SQL Editor**:

1. Go to [supabase.com/dashboard](https://supabase.com/dashboard) → your project → **SQL Editor**
2. Paste and run the contents of `supabase_migration.sql`

This creates:
- `call_logs` table
- `leads` table
- Required indexes and RLS policies

---

## Quick Reference: Environment Variables

| Variable | Where | Description |
|----------|-------|-------------|
| `LIVEKIT_URL` | Railway | LiveKit Cloud WebSocket URL |
| `LIVEKIT_API_KEY` | Railway | LiveKit API key |
| `LIVEKIT_API_SECRET` | Railway | LiveKit API secret |
| `SIP_OUTBOUND_TRUNK_ID` | Railway | Twilio SIP trunk ID |
| `SARVAM_API_KEY` | Railway | Sarvam AI (STT/TTS) |
| `GROQ_API_KEY` | Railway | Groq LLM API key |
| `SUPABASE_URL` | Railway | Supabase project URL |
| `SUPABASE_KEY` | Railway | Supabase service-role key |
| `API_PORT` | Railway | `8081` |
| `API_HOST` | Railway | `0.0.0.0` |
| `NEXT_PUBLIC_API_URL` | Vercel | Railway backend URL |

---

## Deployment Checklist

- [ ] Supabase tables created (`call_logs`, `leads`)
- [ ] Backend deployed on Railway
- [ ] Railway environment variables set
- [ ] Railway health check passing (`/health`)
- [ ] Frontend deployed on Vercel
- [ ] Vercel `NEXT_PUBLIC_API_URL` points to Railway
- [ ] CORS updated in `app/main.py`
- [ ] Test a call from the deployed dashboard
- [ ] Verify leads appear in `/leads` after a call

---

## Troubleshooting

### Backend won't start on Railway
- Check Railway **Deploy Logs** for errors
- Verify all env vars are set (especially `LIVEKIT_URL`, `SARVAM_API_KEY`, `GROQ_API_KEY`)
- Make sure `API_HOST` is `0.0.0.0` (not `127.0.0.1`)

### Frontend shows "Failed to fetch"
- Check that `NEXT_PUBLIC_API_URL` is set correctly in Vercel
- Verify the Railway service is running and accessible
- Check CORS settings in `app/main.py`

### Calls don't connect
- Verify `SIP_OUTBOUND_TRUNK_ID` is correct
- Check that LiveKit Cloud agent is registered
- Verify Twilio SIP trunk is active and configured

### Leads not extracting
- Check `GROQ_API_KEY` is valid and has remaining quota
- Check Railway logs for lead extraction errors
- Run backfill from the dashboard `/leads` page

---

## Cost Estimates (Monthly)

| Service | Free Tier | Paid |
|---------|-----------|------|
| Railway | $5 credit/month | ~$5-20/mo |
| Vercel | Unlimited (hobby) | Free |
| Supabase | 500MB, 50K rows | Free |
| LiveKit Cloud | 50 participant-hours | ~$10+/mo |
| Groq | 100K tokens/day | Free (dev tier ~$0) |
| Sarvam AI | Pay per use | ~$0.01/min |
| Twilio | Pay per call | ~$0.02/min |

**Total estimated cost: $5–30/month** for moderate usage.
