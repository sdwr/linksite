-- ============================================================
-- Nominations Table Migration
-- Run against Supabase with service role key
-- ============================================================

-- Nominations table: tracks user nominations for satellite links
-- Scoped per rotation (rotation_id = started_at timestamp of the rotation)
CREATE TABLE IF NOT EXISTS nominations (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    link_id integer NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    rotation_id text NOT NULL,  -- ties to global_state.started_at of the current rotation
    created_at timestamptz DEFAULT now()
);

-- Index for fast lookup by rotation
CREATE INDEX IF NOT EXISTS idx_nominations_rotation
    ON nominations(rotation_id);

-- Index for fast lookup by link within a rotation
CREATE INDEX IF NOT EXISTS idx_nominations_link_rotation
    ON nominations(link_id, rotation_id);

-- Index for checking if user already nominated in this rotation
CREATE INDEX IF NOT EXISTS idx_nominations_user_rotation
    ON nominations(user_id, rotation_id);

-- Enable RLS (Row Level Security) - optional, depends on your Supabase setup
-- ALTER TABLE nominations ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Allow all for service role" ON nominations FOR ALL USING (true);

-- Cleanup: remove old nominations (optional cron or manual)
-- DELETE FROM nominations WHERE created_at < now() - interval '7 days';
