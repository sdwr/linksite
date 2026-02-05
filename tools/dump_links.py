#!/usr/bin/env python3
"""Dump links with summaries as JSON."""
import os
import json
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
r = sb.table('links').select('id,url,title,description,content,summary').not_.is_('summary', 'null').neq('summary', '').limit(10).execute()
print(json.dumps(r.data, indent=2))
