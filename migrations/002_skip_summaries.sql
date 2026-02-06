-- Migration: Mark summaries as skipped (not processed by worker)
-- Summary generation is not yet implemented in the worker queue
-- Date: 2025-01-20

-- Update all pending summaries to skipped
UPDATE link_processing 
SET summary_status = 'skipped', 
    summary_error = 'Not implemented in worker yet'
WHERE summary_status = 'pending';

-- Keep completed summaries as-is (from previous manual generation)
