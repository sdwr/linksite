import os
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

print("=== Feeds table ===")
resp = sb.table("feeds").select("*").limit(1).execute()
print("Columns:", list(resp.data[0].keys()) if resp.data else "empty")
print("Data:", resp.data)

print("\n=== Links table ===")
resp2 = sb.table("links").select("id,url,title,feed_id").limit(3).execute()
print("Sample:", resp2.data)
print("Has feed_id:", "feed_id" in (list(resp2.data[0].keys()) if resp2.data else []))
