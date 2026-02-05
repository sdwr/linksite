import requests

# Check if summary is in API response
resp = requests.get('https://linksite-dev-bawuw.sprites.app/api/links?limit=10')
data = resp.json()

print("API Response fields check:")
for link in data.get('links', data)[:5]:
    has_summary = 'summary' in link
    summary_val = link.get('summary', '')
    summary_preview = (summary_val[:50] + '...') if summary_val and len(summary_val) > 50 else summary_val
    print(f"ID {link['id']}: has_summary_field={has_summary}, value={repr(summary_preview)}")
