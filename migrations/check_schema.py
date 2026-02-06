#!/usr/bin/env python3
"""Check current database schema."""
import os
os.environ['DATABASE_URL'] = 'postgresql://postgres:nPApeCGY5sdGFzNu@db.rsjcdwmgbxthsuyspndt.supabase.co:5432/postgres'
import sys
sys.path.insert(0, '/home/sprite/linksite')
from db import query

tables = query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
print('Tables:', [t['table_name'] for t in tables])

cols = query("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'links' AND table_schema = 'public' ORDER BY ordinal_position")
print('\nLinks columns:')
for c in cols:
    print(f'  {c["column_name"]}: {c["data_type"]}')

lp = query("SELECT column_name FROM information_schema.columns WHERE table_name = 'link_processing' AND table_schema = 'public'")
if lp:
    print('\nlink_processing exists with columns:', [c['column_name'] for c in lp])
else:
    print('\nlink_processing table does NOT exist yet')
