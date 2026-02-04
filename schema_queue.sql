-- ============================================================
-- Queue-First Processing Infrastructure
-- Run in Supabase SQL Editor
-- ============================================================

-- Links table updates: processing queue columns
ALTER TABLE links ADD COLUMN IF NOT EXISTS processing_status TEXT DEFAULT 'new';
ALTER TABLE links ADD COLUMN IF NOT EXISTS processing_priority INTEGER DEFAULT 1;
ALTER TABLE links ADD COLUMN IF NOT EXISTS last_processed_at TIMESTAMPTZ;

COMMENT ON COLUMN links.processing_status IS 'Queue status: new, processing, completed, failed';
COMMENT ON COLUMN links.processing_priority IS 'Processing priority: higher = processed first. User-submitted = 10, feeds = 1';
COMMENT ON COLUMN links.last_processed_at IS 'Timestamp of last AI processing';

-- Index for efficient worker queue queries
CREATE INDEX IF NOT EXISTS idx_links_processing_queue 
ON links(processing_status, processing_priority DESC, created_at ASC)
WHERE processing_status = 'new';

-- API rate limits / backoff tracking
CREATE TABLE IF NOT EXISTS api_rate_limits (
    api_name TEXT PRIMARY KEY,
    requests_this_window INTEGER DEFAULT 0,
    window_start TIMESTAMPTZ DEFAULT now(),
    backoff_until TIMESTAMPTZ,
    consecutive_failures INTEGER DEFAULT 0,
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    last_error TEXT
);

COMMENT ON TABLE api_rate_limits IS 'Tracks API rate limits and exponential backoff state';

-- Seed initial API entries
INSERT INTO api_rate_limits (api_name) VALUES 
('anthropic'), ('reddit'), ('hackernews')
ON CONFLICT DO NOTHING;

-- Job runs history for admin visibility
CREATE TABLE IF NOT EXISTS job_runs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    job_type TEXT NOT NULL,  -- 'gather_hn', 'gather_reddit', 'process_batch'
    status TEXT DEFAULT 'running',  -- 'running', 'completed', 'failed'
    started_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ,
    items_processed INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

COMMENT ON TABLE job_runs IS 'History of background job executions for monitoring';

CREATE INDEX IF NOT EXISTS idx_job_runs_type_time ON job_runs(job_type, started_at DESC);

-- Set existing links without processing_status to 'completed' 
-- (they were processed under the old system or don't need processing)
UPDATE links SET processing_status = 'completed' 
WHERE processing_status IS NULL OR processing_status = '';

-- Backfill: mark links without summaries as needing processing
UPDATE links SET processing_status = 'new', processing_priority = 1 
WHERE summary IS NULL AND processing_status = 'completed';
