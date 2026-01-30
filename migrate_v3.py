"""Run schema migration v3: Director + voting + tags + global state."""
import os
import requests
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_KEY = "sb_secret_iRByWq7bdLmzzT81Dvh3kA_9P7dNTjZ"

# Supabase SQL API via the /rest/v1/rpc endpoint won't work for DDL.
# We need to use the Management API or psql. Let's try the pg-meta SQL endpoint.
# Supabase exposes a SQL endpoint at: POST /pg/query (needs service key)

# Actually, let's use the Supabase SQL HTTP API
# https://supabase.com/docs/reference/api/sql
sql_url = f"{SUPABASE_URL}/rest/v1/rpc"

# The simplest approach: use psycopg2 to connect directly
import psycopg2

# Supabase direct connection (port 5432 for direct, 6543 for pooler)
# Connection string: postgresql://postgres.[project-ref]:[password]@[host]:5432/postgres
PROJECT_REF = SUPABASE_URL.split("//")[1].split(".")[0]

# Try the pooler connection first
# Actually, we need the DB password. Let's try the Supabase Management API instead.
# Or we can use the pg_net extension via RPC if available.

# Simplest: let's just test if we can use supabase-py with service key for DDL
from supabase import create_client
sb = create_client(SUPABASE_URL, SERVICE_KEY)

# The service role key CAN'T run DDL through PostgREST.
# Let's output the SQL and see if we can use pg-meta or another approach.

migration_sql = """
-- 1. Users
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Votes (append-only log)
CREATE TABLE IF NOT EXISTS votes (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    link_id BIGINT NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    value SMALLINT NOT NULL CHECK (value IN (-1, 1)),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_votes_link_id ON votes(link_id);
CREATE INDEX IF NOT EXISTS idx_votes_created_at ON votes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_votes_link_created ON votes(link_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_votes_user_link ON votes(user_id, link_id, created_at DESC);

-- 3. Tags
CREATE TABLE IF NOT EXISTS tags (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    score FLOAT DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tags_slug ON tags(slug);
CREATE INDEX IF NOT EXISTS idx_tags_score ON tags(score DESC);

-- 4. Feed Tags
CREATE TABLE IF NOT EXISTS feed_tags (
    feed_id BIGINT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    tag_id BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    relevance_score FLOAT DEFAULT 1.0,
    PRIMARY KEY (feed_id, tag_id)
);

-- 5. Links scoring columns
ALTER TABLE links ADD COLUMN IF NOT EXISTS direct_score FLOAT DEFAULT 0.0;
ALTER TABLE links ADD COLUMN IF NOT EXISTS last_shown_at TIMESTAMPTZ;
ALTER TABLE links ADD COLUMN IF NOT EXISTS times_shown INTEGER DEFAULT 0;

-- 6. Feeds trust columns
ALTER TABLE feeds ADD COLUMN IF NOT EXISTS trust_score FLOAT DEFAULT 1.0;
ALTER TABLE feeds ADD COLUMN IF NOT EXISTS avg_link_score FLOAT DEFAULT 0.0;

-- 7. Global State
CREATE TABLE IF NOT EXISTS global_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    current_link_id BIGINT REFERENCES links(id),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    reveal_ends_at TIMESTAMPTZ,
    rotation_ends_at TIMESTAMPTZ,
    selection_reason TEXT,
    satellites JSONB DEFAULT '[]'
);
INSERT INTO global_state (id) VALUES (1) ON CONFLICT DO NOTHING;

-- 8. Director Log
CREATE TABLE IF NOT EXISTS director_log (
    id BIGSERIAL PRIMARY KEY,
    link_id BIGINT REFERENCES links(id),
    reason TEXT NOT NULL,
    momentum_snapshot JSONB,
    duration_seconds INTEGER,
    selected_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_director_log_selected ON director_log(selected_at DESC);

-- 9. Score Weights
CREATE TABLE IF NOT EXISTS score_weights (
    key TEXT PRIMARY KEY,
    value FLOAT NOT NULL,
    description TEXT
);
INSERT INTO score_weights (key, value, description) VALUES
    ('vote_to_tag', 0.3, 'Link vote propagation to each tag'),
    ('vote_to_feed', 0.1, 'Link vote propagation to feed trust'),
    ('pool_fresh', 0.6, 'Selection weight: fresh links'),
    ('pool_rerun', 0.3, 'Selection weight: proven classics'),
    ('pool_wildcard', 0.1, 'Selection weight: random wildcards'),
    ('momentum_window_min', 30, 'Momentum lookback (minutes)'),
    ('rotation_default_sec', 120, 'Default rotation duration'),
    ('reveal_interval_sec', 20, 'Seconds between satellite reveals'),
    ('downvote_skip_threshold', 3, 'Downvotes from 1 user to skip'),
    ('vote_cooldown_sec', 10, 'Cooldown between actions'),
    ('upvote_time_bonus_sec', 15, 'Seconds added per upvote'),
    ('downvote_time_penalty_sec', 20, 'Seconds removed per downvote'),
    ('fatigue_lookback', 20, 'Recent picks for variety check'),
    ('satellite_count', 5, 'Satellites per rotation')
ON CONFLICT (key) DO NOTHING;
"""

print("=== Migration SQL ===")
print(migration_sql)
print("=== End SQL ===")
print()
print(f"Run this in Supabase SQL Editor:")
print(f"https://supabase.com/dashboard/project/{PROJECT_REF}/sql/new")
print()

# Let's try to verify what already exists
print("Checking existing tables...")
tables_to_check = ["users", "votes", "tags", "feed_tags", "global_state", "director_log", "score_weights"]
for t in tables_to_check:
    try:
        resp = sb.table(t).select("*", count="exact").limit(0).execute()
        print(f"  {t}: EXISTS (count={resp.count if hasattr(resp, 'count') else '?'})")
    except Exception as e:
        err = str(e)
        if "does not exist" in err or "42P01" in err:
            print(f"  {t}: MISSING")
        else:
            print(f"  {t}: ERROR - {err[:100]}")

# Check new columns on links
for col in ["direct_score", "last_shown_at", "times_shown"]:
    try:
        sb.table("links").select(col).limit(0).execute()
        print(f"  links.{col}: EXISTS")
    except:
        print(f"  links.{col}: MISSING")

for col in ["trust_score", "avg_link_score"]:
    try:
        sb.table("feeds").select(col).limit(0).execute()
        print(f"  feeds.{col}: EXISTS")
    except:
        print(f"  feeds.{col}: MISSING")
