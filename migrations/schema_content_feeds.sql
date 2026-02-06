-- ============================================================
-- Content Feeds — Schema Migration
-- Tracks external content APIs (quotes, xkcd, memes, etc.)
-- Run in Supabase SQL Editor
-- ============================================================

-- 1. Create content_feeds table for tracking feed sources
CREATE TABLE IF NOT EXISTS content_feeds (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,              -- e.g., 'quotable', 'xkcd', 'smbc'
    feed_type TEXT NOT NULL,                -- 'api', 'rss', 'scrape'
    endpoint_url TEXT NOT NULL,             -- Primary API/RSS URL
    description TEXT,                       -- Human-readable description
    
    -- Fetch tracking
    enabled BOOLEAN DEFAULT TRUE,
    fetch_interval_hours FLOAT DEFAULT 6.0, -- How often to check for new content
    last_fetched_at TIMESTAMPTZ,            -- Last successful fetch
    last_item_id TEXT,                      -- Last seen item ID/hash (for incremental)
    last_item_count INTEGER DEFAULT 0,      -- Number of items found in last fetch
    etag TEXT,                              -- HTTP ETag for caching
    last_modified TEXT,                     -- HTTP Last-Modified for caching
    
    -- Error tracking
    consecutive_errors INTEGER DEFAULT 0,
    last_error TEXT,
    last_error_at TIMESTAMPTZ,
    
    -- Stats
    total_items_fetched INTEGER DEFAULT 0,
    total_items_ingested INTEGER DEFAULT 0,
    
    -- Config (feed-specific settings as JSON)
    config JSONB DEFAULT '{}'::jsonb,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_content_feeds_enabled ON content_feeds(enabled);
CREATE INDEX IF NOT EXISTS idx_content_feeds_last_fetched ON content_feeds(last_fetched_at);
CREATE INDEX IF NOT EXISTS idx_content_feeds_type ON content_feeds(feed_type);

-- Comments
COMMENT ON TABLE content_feeds IS 'External content feeds (APIs, RSS) for quotes, comics, memes, etc.';
COMMENT ON COLUMN content_feeds.name IS 'Unique identifier for the feed (e.g., quotable, xkcd)';
COMMENT ON COLUMN content_feeds.last_item_id IS 'Last processed item ID/hash to avoid duplicates';
COMMENT ON COLUMN content_feeds.config IS 'Feed-specific configuration (batch size, filters, etc.)';

-- 2. Create content_items table for fetched content
-- This stores the raw items before they become links
CREATE TABLE IF NOT EXISTS content_items (
    id BIGSERIAL PRIMARY KEY,
    feed_id BIGINT NOT NULL REFERENCES content_feeds(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,              -- ID from source (e.g., xkcd num, quote ID)
    content_type TEXT NOT NULL,             -- 'quote', 'comic', 'meme', 'image'
    
    -- Core content
    title TEXT,
    content TEXT,                           -- Quote text, alt text, description
    image_url TEXT,                         -- Direct image URL
    source_url TEXT,                        -- Link to original page
    author TEXT,                            -- Quote author, comic artist
    
    -- Metadata
    tags TEXT[],                            -- Tags/categories from source
    meta_json JSONB DEFAULT '{}'::jsonb,    -- Source-specific metadata
    
    -- Processing status
    ingested_to_link_id BIGINT,             -- ID of created link (null if not ingested)
    ingested_at TIMESTAMPTZ,
    
    -- Timestamps
    published_at TIMESTAMPTZ,               -- Original publish date if known
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure uniqueness per feed
    UNIQUE(feed_id, external_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_content_items_feed ON content_items(feed_id);
CREATE INDEX IF NOT EXISTS idx_content_items_type ON content_items(content_type);
CREATE INDEX IF NOT EXISTS idx_content_items_ingested ON content_items(ingested_to_link_id) WHERE ingested_to_link_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_content_items_fetched ON content_items(fetched_at DESC);

-- Comments
COMMENT ON TABLE content_items IS 'Raw content items fetched from external feeds';
COMMENT ON COLUMN content_items.external_id IS 'Unique ID from source to prevent duplicate fetches';
COMMENT ON COLUMN content_items.ingested_to_link_id IS 'Link ID if this item was converted to a link';

-- 3. Auto-update updated_at trigger for content_feeds
CREATE OR REPLACE FUNCTION update_content_feeds_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_content_feeds_updated ON content_feeds;
CREATE TRIGGER trigger_content_feeds_updated
    BEFORE UPDATE ON content_feeds
    FOR EACH ROW
    EXECUTE FUNCTION update_content_feeds_updated_at();

-- 4. Seed initial content feeds
INSERT INTO content_feeds (name, feed_type, endpoint_url, description, fetch_interval_hours, config)
VALUES 
    ('quotable', 'api', 'https://api.quotable.io/quotes/random', 
     'Curated quotes API - no auth required', 12.0,
     '{"batch_size": 10, "tags": []}'::jsonb),
    
    ('xkcd', 'api', 'https://xkcd.com/info.0.json',
     'xkcd webcomic - JSON API for latest comic', 8.0,
     '{"check_latest": true}'::jsonb),
    
    ('smbc', 'rss', 'https://www.smbc-comics.com/comic/rss',
     'Saturday Morning Breakfast Cereal - daily science/philosophy comics', 12.0,
     '{"max_items": 5}'::jsonb)
ON CONFLICT (name) DO NOTHING;
