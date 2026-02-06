-- Verify link_processing migration
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN reddit_status = 'pending' THEN 1 ELSE 0 END) as reddit_pending,
    SUM(CASE WHEN reddit_status = 'completed' THEN 1 ELSE 0 END) as reddit_completed,
    SUM(CASE WHEN reddit_status = 'skipped' THEN 1 ELSE 0 END) as reddit_skipped,
    SUM(CASE WHEN hn_status = 'pending' THEN 1 ELSE 0 END) as hn_pending,
    SUM(CASE WHEN hn_status = 'completed' THEN 1 ELSE 0 END) as hn_completed,
    SUM(CASE WHEN summary_status = 'pending' THEN 1 ELSE 0 END) as summary_pending,
    SUM(CASE WHEN reverse_lookup_status = 'pending' THEN 1 ELSE 0 END) as reverse_pending
FROM link_processing;
