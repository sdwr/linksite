import os
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

print("=== Feed status ===")
feeds = sb.table("feeds").select("*").execute()
for f in feeds.data:
    print(f"  [{f['type']}] {f['url']}")
    print(f"    status={f.get('status')} last_scraped={f.get('last_scraped_at','never')} links={f.get('link_count',0)} error={f.get('last_error')}")

print("\n=== Links (newest 10) ===")
links = sb.table("links").select("id,url,title,feed_id,created_at").order("created_at", desc=True).limit(10).execute()
for l in links.data:
    print(f"  [{l['id']}] {l['title'][:60] if l['title'] else 'No title'} | feed_id={l.get('feed_id')} | {l['url'][:80]}")

print(f"\nTotal links: {len(sb.table('links').select('id').execute().data)}")
