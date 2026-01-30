"""Test all feed types: add feeds via DB, trigger sync, verify results."""
import os
import time
import requests
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()

sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
BASE = "http://localhost:8080"

# Reset youtube feed status
sb.table("feeds").update({"status": "idle", "last_error": None}).eq("id", 1).execute()
print("Reset youtube feed status")

# Add test feeds via the admin API
test_feeds = [
    {"url": "https://hnrss.org/frontpage", "type": "rss"},
    {"url": "https://www.reddit.com/r/programming", "type": "reddit"},
    {"url": "jay.bsky.team", "type": "bluesky"},
]

for feed in test_feeds:
    # Check if already exists
    existing = sb.table("feeds").select("id").eq("url", feed["url"]).execute()
    if existing.data:
        print(f"Feed already exists: {feed['url']}")
        continue
    try:
        resp = requests.post(f"{BASE}/admin/add-feed",
            data={"url": feed["url"], "type": feed["type"]},
            allow_redirects=False)
        print(f"Added feed: {feed['type']} - {feed['url']} (status {resp.status_code})")
    except Exception as e:
        print(f"Error adding {feed['url']}: {e}")

# List all feeds
print("\n=== All feeds ===")
feeds = sb.table("feeds").select("*").execute()
for f in feeds.data:
    print(f"  [{f['id']}] {f['type']}: {f['url']} status={f.get('status')}")

# Sync all feeds
print("\nTriggering sync all...")
try:
    resp = requests.post(f"{BASE}/admin/sync", allow_redirects=False)
    print(f"Sync triggered (status {resp.status_code})")
except Exception as e:
    print(f"Sync error: {e}")

# Wait for sync to complete
print("Waiting 90 seconds for sync to complete...")
time.sleep(90)

# Check results
print("\n=== Feed status after sync ===")
feeds = sb.table("feeds").select("*").execute()
for f in feeds.data:
    print(f"  [{f['id']}] {f['type']}: status={f.get('status')} links={f.get('link_count')} error={f.get('last_error')}")
    print(f"    last_scraped={f.get('last_scraped_at')}")

print("\n=== Links (newest 20) ===")
links = sb.table("links").select("id,url,title,feed_id,meta_json").order("created_at", desc=True).limit(20).execute()
for l in links.data:
    meta = l.get("meta_json", {}) or {}
    ftype = meta.get("type", "?")
    print(f"  [{l['id']}] [{ftype}] feed={l.get('feed_id')} | {(l['title'] or 'No title')[:60]} | {l['url'][:70]}")

total = sb.table("links").select("id", count="exact").execute()
print(f"\nTotal links: {total.count if hasattr(total, 'count') and total.count else len(total.data)}")
