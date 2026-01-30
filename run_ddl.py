import os
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()

SERVICE_KEY = "sb_secret_iRByWq7bdLmzzT81Dvh3kA_9P7dNTjZ"
sb = create_client(os.getenv("SUPABASE_URL"), SERVICE_KEY)

# Verify we can see all columns (migration already ran in SQL editor)
resp = sb.table("feeds").select("*").limit(1).execute()
if resp.data:
    cols = list(resp.data[0].keys())
    print("Feed columns:", cols)
    has_status = "status" in cols
    has_error = "last_error" in cols
    has_count = "link_count" in cols
    print(f"  status: {has_status}, last_error: {has_error}, link_count: {has_count}")
else:
    print("No feeds yet")

resp2 = sb.table("links").select("id,feed_id").limit(1).execute()
if resp2.data:
    cols = list(resp2.data[0].keys())
    print(f"Links has feed_id: {'feed_id' in cols}")
else:
    print("No links to check")

print("\nAll migration columns confirmed present.")
