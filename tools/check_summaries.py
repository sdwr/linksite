#!/usr/bin/env python3
"""Quick check for existing summaries."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client

sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
r = sb.table('links').select('id,title,summary').not_.is_('summary', 'null').neq('summary', '').limit(5).execute()

print(f'Links with summaries: {len(r.data)}')
for l in r.data:
    title = (l.get('title') or '')[:50]
    summary = (l.get('summary') or '')[:100]
    print(f"\n{l['id']}: {title}...")
    print(f"  Summary: {summary}...")
