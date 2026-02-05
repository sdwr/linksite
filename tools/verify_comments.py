#!/usr/bin/env python3
"""Verify seeded comments."""
import json
from db import query

# Count by link
result = query("""
    SELECT link_id, COUNT(*) as total_comments, 
           COUNT(CASE WHEN parent_id IS NULL THEN 1 END) as top_level,
           COUNT(CASE WHEN parent_id IS NOT NULL THEN 1 END) as replies
    FROM comments 
    GROUP BY link_id 
    ORDER BY link_id
""")
print("=== Comments per link ===")
for row in result or []:
    print(f"  Link {row['link_id']}: {row['total_comments']} total ({row['top_level']} comments, {row['replies']} replies)")

# Total count
total = query("SELECT COUNT(*) as cnt FROM comments")
print(f"\nTotal comments in database: {total[0]['cnt'] if total else 0}")

# Sample comments
samples = query("SELECT id, link_id, content FROM comments ORDER BY id LIMIT 5")
print("\n=== Sample comments ===")
for s in samples or []:
    print(f"  [Link {s['link_id']}] {s['content'][:60]}...")
