import requests

# Check links WITH summaries
resp = requests.get(
    'https://linksite-dev-bawuw.sprites.app/api/admin/links-needing-summary?limit=500',
    auth=('admin', 'LinkAdmin2026SecureX9')
)
needs_summary = resp.json()['links']
needs_ids = set(l['id'] for l in needs_summary)

print(f"Links needing summary: {len(needs_ids)}")

# Get all links count via browse endpoint (HTML page, need different approach)
# Let's just check some specific IDs we know should have summaries from testing
test_ids = [237, 235, 234, 233, 230, 229, 226, 195, 176, 171]

print("\nChecking test IDs for summaries:")
for lid in test_ids:
    if lid in needs_ids:
        print(f"  ID {lid}: NO SUMMARY")
    else:
        print(f"  ID {lid}: HAS SUMMARY")
