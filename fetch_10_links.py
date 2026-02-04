#!/usr/bin/env python3
"""Fetch full content for the 10 links we summarized."""
import os
import json
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# The 10 links we summarized
link_ids = [237, 235, 234, 233, 230, 229, 226, 195, 176, 171]

r = sb.table('links').select('id,url,title,content').in_('id', link_ids).execute()

# Sort by original order
links_by_id = {l['id']: l for l in r.data}
ordered = [links_by_id[lid] for lid in link_ids if lid in links_by_id]

print(json.dumps(ordered, indent=2))
