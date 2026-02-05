-- ============================================================
-- RSS Gatherer — Schema Migration
-- Run in Supabase SQL Editor
-- ============================================================

-- 1. Add processing_status and processing_priority columns to links
-- These track link processing state for the content pipeline
ALTER TABLE links ADD COLUMN IF NOT EXISTS processing_status TEXT DEFAULT 'new';
ALTER TABLE links ADD COLUMN IF NOT EXISTS processing_priority INTEGER DEFAULT 0;

COMMENT ON COLUMN links.processing_status IS 'Processing state: new, pending, processing, complete, error';
COMMENT ON COLUMN links.processing_priority IS 'Priority for processing queue (higher = sooner). Gathered links get priority 1.';

-- Add index for efficient queue queries
CREATE INDEX IF NOT EXISTS idx_links_processing_status ON links(processing_status);
CREATE INDEX IF NOT EXISTS idx_links_processing_priority ON links(processing_priority DESC);

-- 2. Create job_runs table to track gather/processing jobs
CREATE TABLE IF NOT EXISTS job_runs (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    job_type TEXT NOT NULL,  -- 'gather', 'process', 'enrich', etc.
    source TEXT,             -- 'hn', 'reddit', 'manual', etc.
    items_found INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,
    items_skipped INTEGER DEFAULT 0,
    items_processed INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]'::jsonb,
    duration_ms INTEGER,
    status TEXT DEFAULT 'running' CHECK (status IN ('running', 'completed', 'completed_with_errors', 'failed')),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_runs_type ON job_runs(job_type);
CREATE INDEX IF NOT EXISTS idx_job_runs_source ON job_runs(source);
CREATE INDEX IF NOT EXISTS idx_job_runs_status ON job_runs(status);
CREATE INDEX IF NOT EXISTS idx_job_runs_created ON job_runs(created_at DESC);

COMMENT ON TABLE job_runs IS 'Tracks gather, processing, and enrichment job runs';
COMMENT ON COLUMN job_runs.job_type IS 'Type of job: gather, process, enrich';
COMMENT ON COLUMN job_runs.source IS 'Source identifier: hn, reddit, manual, etc.';
COMMENT ON COLUMN job_runs.errors IS 'Array of error messages encountered during the job';

-- 3. Add trigger to auto-set completed_at when status changes to completed
CREATE OR REPLACE FUNCTION update_job_run_completed()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IN ('completed', 'completed_with_errors', 'failed') 
       AND OLD.status = 'running' THEN
        NEW.completed_at = NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_job_run_completed ON job_runs;
CREATE TRIGGER trigger_job_run_completed
    BEFORE UPDATE OF status ON job_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_job_run_completed();
