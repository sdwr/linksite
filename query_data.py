#!/usr/bin/env python3
"""Temp script to query users and links with summaries"""
from db import query

print("=== USERS ===")
users = query('SELECT id, display_name FROM users LIMIT 20')
for u in users:
    print(f"USER: {u['id']} | {u['display_name']}")

print("\n=== LINKS WITH SUMMARIES ===")
links = query("SELECT id, url, title, summary FROM links WHERE summary IS NOT NULL AND summary != '' LIMIT 20")
for l in links:
    print(f"LINK {l['id']}: {l['title'][:60] if l['title'] else 'No title'}...")
    print(f"  URL: {l['url'][:80] if l['url'] else 'No URL'}")
    print(f"  SUMMARY: {l['summary'][:150] if l['summary'] else 'No summary'}...")
    print()
