import requests
import re
from bs4 import BeautifulSoup

url = "https://www.youtube.com/videogamedunkey"
print(f"Fetching {url}...")
try:
    resp = requests.get(url, timeout=15, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    print(f"Status: {resp.status_code}")
    print(f"Content length: {len(resp.text)}")
    
    # Try regex
    match = re.search(r'"channelId"\s*:\s*"(UC[\w\-]+)"', resp.text)
    if match:
        print(f"Found channelId via regex: {match.group(1)}")
    else:
        print("No channelId via regex")
    
    # Try link tag
    match2 = re.search(r'channel_id=(UC[\w\-]+)', resp.text)
    if match2:
        print(f"Found channelId via link: {match2.group(1)}")
    else:
        print("No channelId via link tag")
    
    # Try meta tag
    soup = BeautifulSoup(resp.text, 'html.parser')
    meta = soup.find('meta', {'itemprop': 'channelId'})
    if meta:
        print(f"Found channelId via meta: {meta.get('content')}")
    else:
        print("No channelId via meta tag")
    
    # Also try the canonical URL
    canonical = soup.find('link', {'rel': 'canonical'})
    if canonical:
        print(f"Canonical URL: {canonical.get('href')}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# Try direct RSS with known channel ID for dunkey
print("\n--- Testing RSS directly ---")
# dunkey's channel ID is UCsvn_Po0SmunchJYOWpOxMg
rss_url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCsvn_Po0SmunchJYOWpOxMg"
try:
    import feedparser
    parsed = feedparser.parse(rss_url)
    print(f"Feed title: {parsed.feed.get('title', 'N/A')}")
    print(f"Entries: {len(parsed.entries)}")
    if parsed.entries:
        print(f"First entry: {parsed.entries[0].get('title', 'N/A')}")
        print(f"First link: {parsed.entries[0].get('link', 'N/A')}")
except Exception as e:
    print(f"RSS error: {e}")
