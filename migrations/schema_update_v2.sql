-- Schema Update v2: Feed type expansion + sync status + link management
-- Run this in your Supabase SQL Editor

-- 1. Expand feed types
ALTER TABLE feeds DROP CONSTRAINT IF EXISTS feeds_type_check;
ALTER TABLE feeds ADD CONSTRAINT feeds_type_check 
  CHECK (type IN ('rss', 'youtube', 'website', 'reddit', 'bluesky'));

-- 2. Add sync status columns to feeds
ALTER TABLE feeds ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'idle';
ALTER TABLE feeds ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE feeds ADD COLUMN IF NOT EXISTS link_count INTEGER DEFAULT 0;

-- 3. Add feed_id reference to links
ALTER TABLE links ADD COLUMN IF NOT EXISTS feed_id BIGINT REFERENCES feeds(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_links_feed_id ON links(feed_id);

