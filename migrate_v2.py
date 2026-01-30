"""Run schema migration v2 via Supabase RPC / direct SQL."""
import os
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()

sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# We can't run raw SQL via the anon key, so we'll use the REST API approach:
# 1. Add columns to feeds via individual alter-like operations
# 2. Add feed_id to links

# Test if columns already exist by trying to select them
print("Checking feeds table...")
try:
    resp = sb.table("feeds").select("status").limit(1).execute()
    print("  'status' column exists")
except Exception as e:
    print(f"  'status' column missing: {e}")

try:
    resp = sb.table("feeds").select("last_error").limit(1).execute()
    print("  'last_error' column exists")
except Exception as e:
    print(f"  'last_error' column missing: {e}")

try:
    resp = sb.table("feeds").select("link_count").limit(1).execute()
    print("  'link_count' column exists")
except Exception as e:
    print(f"  'link_count' column missing: {e}")

print("\nChecking links table...")
try:
    resp = sb.table("links").select("feed_id").limit(1).execute()
    print("  'feed_id' column exists")
except Exception as e:
    print(f"  'feed_id' column missing: {e}")

print("\nSchema migration SQL must be run in Supabase SQL Editor:")
print("---")
with open("schema_update_v2.sql") as f:
    print(f.read())
print("---")
print("Please run the above SQL in your Supabase dashboard SQL Editor.")
