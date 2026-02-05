import requests
import json

resp = requests.get(
    'https://linksite-dev-bawuw.sprites.app/api/admin/links-needing-summary?limit=200',
    auth=('admin', 'LinkAdmin2026SecureX9')
)
data = resp.json()

print(f"Total needing summary: {data['count']}")
print()

for link in data['links']:
    content_len = len(link.get('content', '') or '')
    print(f"ID {link['id']}: {content_len} chars | {link['url'][:60]}")

# Save full data for processing
with open('links_to_summarize.json', 'w') as f:
    json.dump(data['links'], f, indent=2)
print(f"\nSaved {len(data['links'])} links to links_to_summarize.json")
