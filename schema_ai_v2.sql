-- ============================================================
-- AI Content Engine v2 — Schema Updates
-- Run in Supabase SQL Editor
-- ============================================================

-- 1. Add summary column to links table
ALTER TABLE links ADD COLUMN IF NOT EXISTS summary TEXT;
COMMENT ON COLUMN links.summary IS 'AI-generated summary of the link content';

-- 2. Add persona_id to notes table (for tracking which personality generated AI comments)
ALTER TABLE notes ADD COLUMN IF NOT EXISTS persona_id TEXT;
COMMENT ON COLUMN notes.persona_id IS 'AI persona identifier for AI-generated comments';

-- 3. Add persona_id to ai_generated_content table
ALTER TABLE ai_generated_content ADD COLUMN IF NOT EXISTS persona_id TEXT;
COMMENT ON COLUMN ai_generated_content.persona_id IS 'AI persona identifier used for generation';

-- 4. Add engagement metrics to links if not present
ALTER TABLE links ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0;
ALTER TABLE links ADD COLUMN IF NOT EXISTS engagement_score FLOAT DEFAULT 0;
COMMENT ON COLUMN links.view_count IS 'Number of times this link was featured/viewed';
COMMENT ON COLUMN links.engagement_score IS 'Calculated engagement score for prioritization';

-- 5. Create AI token usage tracking table
CREATE TABLE IF NOT EXISTS ai_token_usage (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    run_id uuid REFERENCES ai_runs(id) ON DELETE SET NULL,
    model text NOT NULL,
    input_tokens integer DEFAULT 0,
    output_tokens integer DEFAULT 0,
    total_tokens integer DEFAULT 0,
    estimated_cost_usd numeric(10,6) DEFAULT 0,
    operation_type text,  -- 'summary', 'comment', 'description', 'tags', 'discovery'
    link_id bigint REFERENCES links(id) ON DELETE SET NULL,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_token_usage_run ON ai_token_usage(run_id);
CREATE INDEX IF NOT EXISTS idx_ai_token_usage_model ON ai_token_usage(model);
CREATE INDEX IF NOT EXISTS idx_ai_token_usage_created ON ai_token_usage(created_at DESC);

COMMENT ON TABLE ai_token_usage IS 'Detailed token usage tracking for AI operations';

-- 6. Create AI personas configuration table
CREATE TABLE IF NOT EXISTS ai_personas (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    system_prompt TEXT,
    user_prompt_template TEXT,
    model TEXT DEFAULT 'haiku',
    is_active BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 50,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

COMMENT ON TABLE ai_personas IS 'Configurable AI personas for generating comments';

-- Insert default personas
INSERT INTO ai_personas (id, name, description, system_prompt, model, priority) VALUES
('summary', 'Summarizer', 'Generates brief TL;DR summaries', 'You write concise, informative TL;DR summaries.', 'haiku', 100),
('technical', 'Technical Analyst', 'Deep technical analysis', 'You are a technical expert who provides insightful analysis of technology and implementation details.', 'sonnet', 80),
('business', 'Business Analyst', 'Business and market implications', 'You analyze business models, market dynamics, and strategic implications.', 'haiku', 60),
('contrarian', 'Devils Advocate', 'Challenges assumptions and finds weaknesses', 'You are a thoughtful contrarian who challenges assumptions and explores counterarguments.', 'sonnet', 40)
ON CONFLICT (id) DO NOTHING;

-- 7. Add trigger to update engagement_score
CREATE OR REPLACE FUNCTION update_engagement_score()
RETURNS TRIGGER AS $$
BEGIN
    NEW.engagement_score = COALESCE(NEW.direct_score, 0) * 0.3 + 
                           COALESCE(NEW.times_shown, 0) * 0.2 + 
                           COALESCE(NEW.view_count, 0) * 0.1 +
                           CASE WHEN NEW.created_at > NOW() - INTERVAL '7 days' THEN 30 
                                WHEN NEW.created_at > NOW() - INTERVAL '30 days' THEN 15
                                ELSE 0 END;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_engagement_score ON links;
CREATE TRIGGER trigger_engagement_score
    BEFORE INSERT OR UPDATE OF direct_score, times_shown, view_count ON links
    FOR EACH ROW
    EXECUTE FUNCTION update_engagement_score();
