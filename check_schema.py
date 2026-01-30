import os
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
resp = sb.table("feeds").select("*").limit(1).execute()
print("Feeds columns:", list(resp.data[0].keys()) if resp.data else "empty")
print("Feed data:", resp.data)

resp2 = sb.table("links").select("*").limit(1).execute()
print("Links columns:", list(resp2.data[0].keys()) if resp2.data else "empty")
