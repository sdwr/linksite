#!/usr/bin/env python3
from db import query

# Count by processing status
result = query("SELECT processing_status, COUNT(*) as cnt FROM links GROUP BY processing_status ORDER BY cnt DESC")
print("=== Processing Status Counts ===")
for row in result:
    print(f"  {row['processing_status']}: {row['cnt']}")

# Check stuck 'processing' links
stuck = query("SELECT id, url, processing_status, created_at FROM links WHERE processing_status = 'processing'")
print(f"\n=== Stuck in 'processing' ({len(stuck)}) ===")
for row in stuck:
    print(f"  ID {row['id']}: {row['url'][:60]}...")

# Check if there are links without summary that are marked completed
no_summary = query("""
    SELECT id, url, processing_status, summary 
    FROM links 
    WHERE processing_status = 'completed' AND (summary IS NULL OR summary = '')
    LIMIT 10
""")
print(f"\n=== Completed but no summary ({len(no_summary)} shown) ===")
for row in no_summary:
    print(f"  ID {row['id']}: {row['url'][:60]}...")
