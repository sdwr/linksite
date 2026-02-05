#!/usr/bin/env python3
"""Show links table schema."""
import sys
import os
from dotenv import load_dotenv

# Load .env from linksite directory
load_dotenv('/home/sprite/linksite/.env')

sys.path.insert(0, '/home/sprite/linksite')
from db import query

cols = query("""
    SELECT column_name, data_type, column_default
    FROM information_schema.columns 
    WHERE table_name = 'links' 
    ORDER BY ordinal_position
""")

print("=== links table columns ===")
for c in cols:
    default = f" DEFAULT {c['column_default']}" if c['column_default'] else ""
    print(f"  {c['column_name']}: {c['data_type']}{default}")

# Also show external_discussions
cols2 = query("""
    SELECT column_name, data_type, column_default
    FROM information_schema.columns 
    WHERE table_name = 'external_discussions' 
    ORDER BY ordinal_position
""")

print("\n=== external_discussions table columns ===")
for c in cols2:
    default = f" DEFAULT {c['column_default']}" if c['column_default'] else ""
    print(f"  {c['column_name']}: {c['data_type']}{default}")
