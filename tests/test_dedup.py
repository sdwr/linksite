"""Test deduplication: re-sync should add 0 new links."""
import os, time, requests
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# Count before
before = len(sb.table("links").select("id").execute().data)
print(f"Links before re-sync: {before}")

# Trigger sync all
requests.post("http://localhost:8080/admin/sync", allow_redirects=False)
print("Re-sync triggered, waiting 90s...")
time.sleep(90)

# Count after
after = len(sb.table("links").select("id").execute().data)
print(f"Links after re-sync: {after}")
print(f"New links added: {after - before}")

if after == before:
    print("PASS: Deduplication works correctly!")
else:
    print("WARN: Some duplicates were added")
