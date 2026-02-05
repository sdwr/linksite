import requests

# Check specific IDs we know have summaries
test_ids = [237, 235, 234, 233, 230, 229, 226, 195, 176, 171]

resp = requests.get('https://linksite-dev-bawuw.sprites.app/api/links?limit=200')
data = resp.json()
links = data.get('links', data)

link_map = {l['id']: l for l in links}

print("Summary status for test IDs:")
for lid in test_ids:
    if lid in link_map:
        summary = link_map[lid].get('summary', '')
        has_summary = bool(summary and len(summary) > 20)
        preview = (summary[:60] + '...') if summary and len(summary) > 60 else summary
        print(f"ID {lid}: has_summary={has_summary} | {repr(preview)}")
    else:
        print(f"ID {lid}: NOT IN RESPONSE (might be too old)")
