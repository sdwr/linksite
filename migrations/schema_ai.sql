-- ============================================================
-- AI Content Engine â€” Database Schema
-- Run in Supabase SQL Editor with service role key
-- ============================================================

-- AI Runs: tracks every engine invocation
CREATE TABLE IF NOT EXISTS ai_runs (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    type text NOT NULL CHECK (type IN ('discover', 'enrich')),
    params jsonb DEFAULT '{}'::jsonb,
    results_count integer DEFAULT 0,
    tokens_used integer DEFAULT 0,
    model text,
    status text DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    error text,
    created_at timestamptz DEFAULT now(),
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_ai_runs_type ON ai_runs(type);
CREATE INDEX IF NOT EXISTS idx_ai_runs_status ON ai_runs(status);
CREATE INDEX IF NOT EXISTS idx_ai_runs_created ON ai_runs(created_at DESC);

COMMENT ON TABLE ai_runs IS 'Tracks every AI engine invocation (discovery or enrichment)';


-- AI Generated Content: individual pieces of content produced
CREATE TABLE IF NOT EXISTS ai_generated_content (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    run_id uuid REFERENCES ai_runs(id) ON DELETE CASCADE,
    link_id bigint REFERENCES links(id) ON DELETE CASCADE,
    content_type text NOT NULL CHECK (content_type IN ('description', 'comment', 'tag', 'summary', 'related')),
    content text NOT NULL,
    author text,  -- e.g. 'ai-analyst', 'ai-technical', 'ai-contrarian'
    model_used text,
    tokens_used integer DEFAULT 0,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_content_run ON ai_generated_content(run_id);
CREATE INDEX IF NOT EXISTS idx_ai_content_link ON ai_generated_content(link_id);
CREATE INDEX IF NOT EXISTS idx_ai_content_type ON ai_generated_content(content_type);
CREATE INDEX IF NOT EXISTS idx_ai_content_created ON ai_generated_content(created_at DESC);

COMMENT ON TABLE ai_generated_content IS 'Individual pieces of AI-generated content (descriptions, comments, tags)';
COMMENT ON COLUMN ai_generated_content.author IS 'Attribution for the AI persona that generated this content';
