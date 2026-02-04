-- ============================================================
-- Admin Dashboard Improvements Migration
-- Run in Supabase SQL Editor
-- ============================================================

-- 1. Add reddit_api_stats JSONB column to global_state for persistence
ALTER TABLE global_state ADD COLUMN IF NOT EXISTS reddit_api_stats JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN global_state.reddit_api_stats IS 'Persisted Reddit API statistics (calls, searches, resolves, etc.)';

-- 2. Add links_processed JSONB column to job_runs for tracking processed link IDs
ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS links_processed JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN job_runs.links_processed IS 'Array of link IDs processed in this job run';

-- 3. Add index for efficient job run queries by type and status
CREATE INDEX IF NOT EXISTS idx_job_runs_type_status ON job_runs(job_type, status);

-- 4. Ensure started_at column exists (it should, but be safe)
ALTER TABLE job_runs ALTER COLUMN started_at SET DEFAULT NOW();
