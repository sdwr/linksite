-- Migration: Create link_processing table
-- Purpose: Separate processing state from main links table
--          Enables per-task status tracking (Reddit, HN, Summary, Reverse Lookup)
--          Reduces dead tuples in links table from worker updates
-- Date: 2025-01-20

-- Create the link_processing table
CREATE TABLE IF NOT EXISTS link_processing (
    link_id BIGINT PRIMARY KEY REFERENCES links(id) ON DELETE CASCADE,
    
    -- Reddit discussion lookup
    reddit_status TEXT DEFAULT 'pending',  -- pending, completed, not_found, failed, skipped
    reddit_checked_at TIMESTAMPTZ,
    reddit_error TEXT,
    
    -- HN discussion lookup  
    hn_status TEXT DEFAULT 'pending',      -- pending, completed, not_found, failed, skipped
    hn_checked_at TIMESTAMPTZ,
    hn_error TEXT,
    
    -- AI summary generation
    summary_status TEXT DEFAULT 'pending', -- pending, completed, skipped, failed
    summary_generated_at TIMESTAMPTZ,
    summary_error TEXT,
    
    -- For reverse lookup (Reddit/HN URL → original article)
    -- NULL = not a discussion URL (no reverse lookup needed)
    -- pending = needs to be resolved
    -- completed = resolved successfully
    -- not_found = is a self-post or couldn't resolve
    -- failed = API error
    reverse_lookup_status TEXT,
    reverse_lookup_target_id BIGINT REFERENCES links(id),
    
    -- General tracking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Priority: higher = process first (user-submitted = 10, auto = 1)
    priority INTEGER DEFAULT 5
);

-- Add comment for documentation
COMMENT ON TABLE link_processing IS 
    'Processing state for links. 1-to-1 with links table. Isolates worker churn from main table.';

COMMENT ON COLUMN link_processing.reddit_status IS 'pending=needs check, completed=found discussions, not_found=no discussions, failed=API error, skipped=intentionally skipped';
COMMENT ON COLUMN link_processing.reverse_lookup_status IS 'NULL=not a discussion URL, pending=needs resolving, completed=resolved to target_id, not_found=self-post, failed=error';

-- Index for worker: find links needing Reddit lookup
CREATE INDEX IF NOT EXISTS idx_link_processing_reddit_pending 
ON link_processing(priority DESC, created_at) 
WHERE reddit_status = 'pending';

-- Index for worker: find links needing HN lookup
CREATE INDEX IF NOT EXISTS idx_link_processing_hn_pending 
ON link_processing(priority DESC, created_at) 
WHERE hn_status = 'pending';

-- Index for worker: find links needing summary
CREATE INDEX IF NOT EXISTS idx_link_processing_summary_pending 
ON link_processing(priority DESC, created_at) 
WHERE summary_status = 'pending';

-- Index for reverse lookup queue (highest priority)
CREATE INDEX IF NOT EXISTS idx_link_processing_reverse_pending
ON link_processing(created_at)
WHERE reverse_lookup_status = 'pending';

-- Index for finding target of reverse lookup
CREATE INDEX IF NOT EXISTS idx_link_processing_reverse_target
ON link_processing(reverse_lookup_target_id)
WHERE reverse_lookup_target_id IS NOT NULL;

-- Function to auto-update updated_at
CREATE OR REPLACE FUNCTION update_link_processing_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at
DROP TRIGGER IF EXISTS link_processing_updated_at ON link_processing;
CREATE TRIGGER link_processing_updated_at
    BEFORE UPDATE ON link_processing
    FOR EACH ROW
    EXECUTE FUNCTION update_link_processing_updated_at();

-- ============================================================
-- Backfill: Create processing rows for existing links
-- ============================================================

-- Insert processing rows for all existing links that don't have one
-- Set initial statuses based on existing data
INSERT INTO link_processing (link_id, reddit_status, hn_status, summary_status, priority, created_at)
SELECT 
    l.id,
    -- Reddit: check if we already have reddit discussions
    CASE 
        WHEN EXISTS (SELECT 1 FROM external_discussions ed WHERE ed.link_id = l.id AND ed.platform = 'reddit') 
        THEN 'completed'
        WHEN l.source IN ('auto-parent', 'discussion-ref') THEN 'skipped'
        ELSE 'pending'
    END as reddit_status,
    -- HN: check if we already have HN discussions  
    CASE 
        WHEN EXISTS (SELECT 1 FROM external_discussions ed WHERE ed.link_id = l.id AND ed.platform = 'hackernews') 
        THEN 'completed'
        WHEN l.source IN ('auto-parent', 'discussion-ref') THEN 'skipped'
        ELSE 'pending'
    END as hn_status,
    -- Summary: check if link already has a summary
    CASE 
        WHEN l.summary IS NOT NULL AND length(l.summary) > 20 THEN 'completed'
        WHEN l.source IN ('auto-parent', 'discussion-ref') THEN 'skipped'
        ELSE 'pending'
    END as summary_status,
    -- Priority based on source
    CASE 
        WHEN l.source = 'agent' THEN 10
        WHEN l.submitted_by NOT IN ('auto', 'gatherer', '') AND l.submitted_by IS NOT NULL THEN 8
        WHEN l.created_at > NOW() - INTERVAL '24 hours' THEN 5
        ELSE 1
    END as priority,
    l.created_at
FROM links l
WHERE NOT EXISTS (SELECT 1 FROM link_processing lp WHERE lp.link_id = l.id)
ON CONFLICT (link_id) DO NOTHING;

-- Update checked_at for completed statuses
UPDATE link_processing lp
SET reddit_checked_at = NOW()
WHERE reddit_status = 'completed' AND reddit_checked_at IS NULL;

UPDATE link_processing lp
SET hn_checked_at = NOW()
WHERE hn_status = 'completed' AND hn_checked_at IS NULL;

UPDATE link_processing lp
SET summary_generated_at = l.last_processed_at
FROM links l
WHERE lp.link_id = l.id 
  AND lp.summary_status = 'completed' 
  AND lp.summary_generated_at IS NULL
  AND l.last_processed_at IS NOT NULL;
