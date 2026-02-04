import json

with open('links_to_summarize.json') as f:
    links = json.load(f)

# Show samples in different ranges
print("=== Links with 100-300 chars ===\n")
for link in links[:20]:
    clen = len(link.get('content', '') or '')
    if 100 < clen < 300:
        print(f"ID {link['id']} ({clen} chars): {link['url'][:60]}")
        print(f"  Content: {link['content'][:150]}...")
        print()
