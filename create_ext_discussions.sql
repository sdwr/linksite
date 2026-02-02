-- External Discussions table
-- Run this in Supabase SQL Editor or via psycopg2 with pooler connection

CREATE TABLE IF NOT EXISTS external_discussions (
    id BIGSERIAL PRIMARY KEY,
    link_id BIGINT REFERENCES links(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK (platform IN ('hackernews', 'reddit')),
    external_url TEXT NOT NULL,
    external_id TEXT,
    title TEXT,
    score INT DEFAULT 0,
    num_comments INT DEFAULT 0,
    subreddit TEXT,
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    external_created_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(link_id, platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_ext_disc_link_id ON external_discussions(link_id);
