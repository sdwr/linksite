#!/usr/bin/env python3
"""Test scraping various URLs to identify what's blocked."""
import sys
sys.path.insert(0, '/home/sprite/linksite')

from ingest import ContentExtractor

extractor = ContentExtractor()

test_urls = [
    ('https://youtube.com/watch?v=dQw4w9WgXcQ', 'YouTube'),
    ('https://www.bbc.com/news', 'BBC News'),
    ('https://arstechnica.com', 'Ars Technica'),
    ('https://medium.com/', 'Medium'),
    ('https://x.com/elonmusk', 'Twitter/X'),
    ('https://www.linkedin.com/feed/', 'LinkedIn'),
    ('https://www.cloudflare.com/', 'Cloudflare'),
    ('https://news.ycombinator.com/', 'Hacker News'),
    ('https://www.reddit.com/r/programming/', 'Reddit'),
    ('https://github.com/trending', 'GitHub'),
]

print("=" * 60)
print("SCRAPING TEST RESULTS")
print("=" * 60)

for url, name in test_urls:
    try:
        if 'youtube.com/watch' in url or 'youtu.be/' in url:
            result = extractor.extract_youtube_content(url)
            content_len = len(result.get('transcript', '') or result.get('content', '') or '')
            has_transcript = bool(result.get('transcript'))
        else:
            result = extractor.extract_website_content(url)
            content_len = len(result.get('content', '') or result.get('main_text', '') or '')
            has_transcript = None
        
        title = result.get('title', '')[:60] if result.get('title') else '(no title)'
        status = 'OK' if content_len > 100 else 'WEAK' if content_len > 0 else 'EMPTY'
        
        extra = f", transcript={has_transcript}" if has_transcript is not None else ""
        print(f"{status}: {name:15} - {content_len:5} chars - {title}{extra}")
        
    except Exception as e:
        print(f"FAIL: {name:15} - {str(e)[:60]}")

print("=" * 60)
