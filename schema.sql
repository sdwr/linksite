-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the links table
CREATE TABLE IF NOT EXISTS links (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    meta_json JSONB DEFAULT '{}'::jsonb,
    content_vector vector(384),  -- all-MiniLM-L6-v2 produces 384-dimensional vectors
    comment_vector vector(384),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_links_url ON links(url);
CREATE INDEX IF NOT EXISTS idx_links_content_vector ON links USING ivfflat (content_vector vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_links_comment_vector ON links USING ivfflat (comment_vector vector_cosine_ops) WITH (lists = 100);

-- Create a function to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to auto-update updated_at
CREATE TRIGGER update_links_updated_at
    BEFORE UPDATE ON links
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add comment to the table
COMMENT ON TABLE links IS 'Stores ingested links with their content vectors for the link discovery game';
COMMENT ON COLUMN links.meta_json IS 'Stores metadata like og:image, channel_name, etc.';
COMMENT ON COLUMN links.content_vector IS 'Vector embedding of the main content (text/transcript)';
COMMENT ON COLUMN links.comment_vector IS 'Averaged vector embedding of user comments';
