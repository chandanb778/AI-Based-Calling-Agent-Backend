-- ════════════════════════════════════════════════════════════════
--  Supabase Migration: Create call_logs table
-- ════════════════════════════════════════════════════════════════
--
--  Run this in your Supabase SQL Editor:
--    https://supabase.com → Project → SQL Editor → New Query
--
-- ════════════════════════════════════════════════════════════════

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create the call_logs table
CREATE TABLE IF NOT EXISTS call_logs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    caller_number    TEXT        NOT NULL,
    duration_seconds FLOAT8      NOT NULL DEFAULT 0,
    transcript       TEXT        NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast pagination (newest first)
CREATE INDEX IF NOT EXISTS idx_call_logs_created_at
    ON call_logs (created_at DESC);

-- Index for looking up calls by phone number
CREATE INDEX IF NOT EXISTS idx_call_logs_caller_number
    ON call_logs (caller_number);

-- Enable Row Level Security (recommended by Supabase)
ALTER TABLE call_logs ENABLE ROW LEVEL SECURITY;

-- Policy: allow full access from service role (your backend)
-- If you're using the anon key, create a more restrictive policy instead.
CREATE POLICY "Allow service role full access"
    ON call_logs
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ════════════════════════════════════════════════════════════════
--  Done! Your call_logs table is ready.
-- ════════════════════════════════════════════════════════════════


-- ════════════════════════════════════════════════════════════════
--  Supabase Migration: Create leads table
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS leads (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT        NOT NULL DEFAULT 'unknown',
    phone           TEXT        NOT NULL DEFAULT 'unknown',
    budget          TEXT        NOT NULL DEFAULT 'unknown',
    location        TEXT        NOT NULL DEFAULT 'unknown',
    property_type   TEXT        NOT NULL DEFAULT 'unknown',
    timeline        TEXT        NOT NULL DEFAULT 'unknown',
    loan_required   TEXT        NOT NULL DEFAULT 'unknown',
    decision_maker  TEXT        NOT NULL DEFAULT 'unknown',
    lead_score      TEXT        NOT NULL DEFAULT 'COLD',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast pagination (newest first)
CREATE INDEX IF NOT EXISTS idx_leads_created_at
    ON leads (created_at DESC);

-- Index for filtering by lead score
CREATE INDEX IF NOT EXISTS idx_leads_score
    ON leads (lead_score);

-- Index for phone number lookups
CREATE INDEX IF NOT EXISTS idx_leads_phone
    ON leads (phone);

-- Enable Row Level Security
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;

-- Policy: allow full access from service role
CREATE POLICY "Allow service role full access on leads"
    ON leads
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ════════════════════════════════════════════════════════════════
--  Done! Both call_logs and leads tables are ready.
-- ════════════════════════════════════════════════════════════════
