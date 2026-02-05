-- Migration: Add rate limiting columns to api_rate_limits table
-- Run this on Supabase SQL Editor or via psql

-- Add requests_this_window column (for rolling window rate limiting)
ALTER TABLE api_rate_limits 
ADD COLUMN IF NOT EXISTS requests_this_window INTEGER DEFAULT 0;

-- Add window_start column (when the current rate limit window started)
ALTER TABLE api_rate_limits 
ADD COLUMN IF NOT EXISTS window_start TIMESTAMPTZ DEFAULT now();

-- Ensure reddit entry exists
INSERT INTO api_rate_limits (api_name, requests_this_window, window_start)
VALUES ('reddit', 0, now())
ON CONFLICT (api_name) DO UPDATE SET
    requests_this_window = COALESCE(api_rate_limits.requests_this_window, 0),
    window_start = COALESCE(api_rate_limits.window_start, now());

-- Ensure anthropic entry exists  
INSERT INTO api_rate_limits (api_name, requests_this_window, window_start)
VALUES ('anthropic', 0, now())
ON CONFLICT (api_name) DO UPDATE SET
    requests_this_window = COALESCE(api_rate_limits.requests_this_window, 0),
    window_start = COALESCE(api_rate_limits.window_start, now());

-- Ensure hackernews entry exists
INSERT INTO api_rate_limits (api_name, requests_this_window, window_start)
VALUES ('hackernews', 0, now())
ON CONFLICT (api_name) DO UPDATE SET
    requests_this_window = COALESCE(api_rate_limits.requests_this_window, 0),
    window_start = COALESCE(api_rate_limits.window_start, now());
