import requests
import json

resp = requests.get("https://linksite-dev-bawuw.sprites.app/links?limit=200")
data = resp.json()
links = data.get('links', data) if isinstance(data, dict) else data

print(f'Total links: {len(links)}')
print()

needs_summary = []
for link in links:
    has_summary = 'YES' if link.get('summary') else 'NO'
    has_content = 'YES' if link.get('content') else 'NO'
    print(f"ID {link['id']}: content={has_content} summary={has_summary} | {link['url'][:50]}")
    
    if link.get('content') and not link.get('summary'):
        needs_summary.append(link)

print()
print(f"Links needing summary: {len(needs_summary)}")
for link in needs_summary:
    print(f"  ID {link['id']}: {link['url'][:60]}")
