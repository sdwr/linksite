#!/usr/bin/env python3
"""Show the comments table schema."""
import json
from db import query

# Check comments table
result = query("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'comments'
    ORDER BY ordinal_position
""")
print("=== comments table ===")
for row in result or []:
    print(f"  {row['column_name']}: {row['data_type']} (nullable: {row['is_nullable']})")

# Check notes table too
result = query("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'notes'
    ORDER BY ordinal_position
""")
print("\n=== notes table ===")
for row in result or []:
    print(f"  {row['column_name']}: {row['data_type']} (nullable: {row['is_nullable']})")

# Sample data from comments if any
sample = query("SELECT * FROM comments LIMIT 3")
print(f"\n=== sample comments ({len(sample) if sample else 0}) ===")
for row in sample or []:
    print(json.dumps(dict(row), default=str, indent=2))
