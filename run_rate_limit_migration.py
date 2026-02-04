"""Run the rate limit migration on the database using existing db module."""
from db import execute, query

# Add columns (use raw SQL since we can't do ALTER via PostgREST)
# Instead, let's just ensure the API entries exist and check column status

# Test if columns exist by trying to select them
try:
    result = query("SELECT api_name, requests_this_window, window_start FROM api_rate_limits LIMIT 1")
    print(f"Columns already exist! Current data: {result}")
except Exception as e:
    print(f"Columns may not exist yet: {e}")
    print("Run the migrate_rate_limits.sql in Supabase SQL Editor manually")
    exit(1)

# Ensure API entries exist (upsert)
apis = ['reddit', 'anthropic', 'hackernews']
for api in apis:
    try:
        execute(
            """
            INSERT INTO api_rate_limits (api_name, requests_this_window, window_start)
            VALUES (%s, 0, now())
            ON CONFLICT (api_name) DO UPDATE SET
                requests_this_window = COALESCE(api_rate_limits.requests_this_window, 0)
            """,
            (api,)
        )
        print(f"Ensured {api} entry exists")
    except Exception as e:
        print(f"Error with {api}: {e}")

# Verify
result = query("SELECT api_name, requests_this_window, window_start FROM api_rate_limits")
print(f"Current api_rate_limits: {result}")
print("Migration check complete!")
