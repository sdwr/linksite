import json
import requests

# Load links
with open('links_to_summarize.json') as f:
    links = json.load(f)

# Filter to links with substantial content (>300 chars)
substantial = [l for l in links if len(l.get('content', '') or '') > 300]
print(f"Links with >300 chars content: {len(substantial)}")

for link in substantial:
    print(f"  ID {link['id']}: {len(link['content'])} chars | {link['url'][:50]}")

# Save filtered list
with open('links_substantial.json', 'w') as f:
    json.dump(substantial, f, indent=2)

print(f"\nSaved to links_substantial.json")
