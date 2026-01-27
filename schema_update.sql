-- Schema Update for Feed Ingestion System
-- Run this in your Supabase SQL Editor

-- Add content/description column to links table
ALTER TABLE links ADD COLUMN IF NOT EXISTS content TEXT;

-- Add comment for the new column
COMMENT ON COLUMN links.content IS 'Main text content or description of the link';

-- Create feeds table
CREATE TABLE IF NOT EXISTS feeds (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    last_scraped_at TIMESTAMP WITH TIME ZONE,
    type TEXT NOT NULL CHECK (type IN ('rss', 'youtube', 'website')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for feeds table
CREATE INDEX IF NOT EXISTS idx_feeds_type ON feeds(type);
CREATE INDEX IF NOT EXISTS idx_feeds_last_scraped ON feeds(last_scraped_at);

-- Create trigger to auto-update updated_at for feeds
CREATE TRIGGER update_feeds_updated_at
    BEFORE UPDATE ON feeds
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add comments to feeds table
COMMENT ON TABLE feeds IS 'RSS feeds and sources to monitor for new content';
COMMENT ON COLUMN feeds.url IS 'Feed URL or source URL';
COMMENT ON COLUMN feeds.last_scraped_at IS 'Timestamp of last successful scrape';
COMMENT ON COLUMN feeds.type IS 'Type of feed: rss, youtube, or website';
