# Scraping Workarounds Research

## Summary

Testing performed from Fly.io Sprite (cloud IP) on 2025-02-06.

| Site | Status | Content Quality | Issue |
|------|--------|-----------------|-------|
| YouTube | ✅ FIXED | Full transcripts via youtube-transcript-api | yt-dlp blocked, but transcript API works |
| BBC News | ✅ OK | 6953 chars | trafilatura works |
| Ars Technica | ✅ OK | 3207 chars | trafilatura works |
| Hacker News | ✅ OK | 3845 chars | trafilatura works |
| Cloudflare | ✅ OK | 2262 chars | trafilatura works |
| GitHub | ⚠️ WEAK | 967 chars | Minimal content extracted |
| Reddit | ⚠️ WEAK | 741 chars | Minimal content (already using API for feeds) |
| Twitter/X | ⚠️ WEAK | 293 chars, no title | Login wall, minimal content |
| LinkedIn | ⚠️ WEAK | 223 chars | Login wall |
| Medium | ❌ BLOCKED | 0 chars | Complete fetch failure |

## YouTube: SOLVED ✅

### Problem
- yt-dlp is blocked on cloud IPs ("confirm not a bot")
- All public Invidious instances are dead
- oEmbed API only provides metadata (title, channel, thumbnail), no transcript

### Solution: youtube-transcript-api
The `youtube-transcript-api` Python library works from cloud IPs!

**Install:**
```bash
pip install youtube-transcript-api
```

**Usage:**
```python
from youtube_transcript_api import YouTubeTranscriptApi

ytt_api = YouTubeTranscriptApi()
result = ytt_api.fetch(video_id)
text = ' '.join([s.text for s in result.snippets])
```

**Caveats:**
- Rate limited after multiple rapid requests (fine for single-link submissions)
- Not all videos have transcripts (auto-generated or manually created)
- Some videos have transcripts disabled

**Implemented:** Yes, added as fallback in `ingest.py`

### Alternatives Considered (Not Needed)
- **YouTube Data API**: Official, requires API key, doesn't provide transcripts directly
- **Proxy services**: Costly, complex to maintain
- **Cookie-based yt-dlp auth**: Fragile, requires user cookies

## Medium: BLOCKED ❌

### Problem
- Complete fetch failure from cloud IPs
- Aggressive anti-bot protection

### Potential Workarounds
1. **Archive.org fallback**: Check if article is archived
2. **cloudscraper library**: May bypass some Cloudflare challenges
3. **Proxy services**: Residential proxies can work but costly
4. **User-submitted content**: Accept paste of article text

### Recommendation
For now, Medium links will have minimal content (just title/description). 
Consider adding an Archive.org fallback for future improvement.

## Twitter/X: WEAK ⚠️

### Problem
- Login wall blocks most content
- Only 293 chars extracted, no title

### Potential Workarounds
1. **Nitter instances**: Some still work, but unreliable
2. **Twitter API v2**: Requires developer account, rate limited
3. **Archive.org fallback**: Check for archived versions
4. **Accept minimal content**: Title + short description may be enough

### Recommendation
Accept minimal content for tweets. The link URL itself often contains enough context.

## LinkedIn: WEAK ⚠️

### Problem  
- Aggressive login wall
- Only returns login page content (223 chars)

### Potential Workarounds
1. **LinkedIn API**: Requires OAuth, complex setup
2. **Accept minimal content**: Most LinkedIn links are self-explanatory
3. **User-submitted summaries**: Let users describe the content

### Recommendation
Accept minimal content. LinkedIn links in linksite are typically shared for the topic,
not the full article content.

## General Anti-Bot Bypass Options

### cloudscraper
```bash
pip install cloudscraper
```
Automatically handles Cloudflare challenges. Worth trying for Medium.

### undetected-chromedriver
Headless Chrome that evades detection. Heavy dependency, not suitable for Fly.io Sprites.

### Playwright/Puppeteer
Full browser automation. Possible but heavy for a simple scraper.

### Archive.org Fallback
```python
def try_archive_org(url):
    archive_url = f"https://archive.org/wayback/available?url={url}"
    resp = requests.get(archive_url)
    data = resp.json()
    if data.get('archived_snapshots', {}).get('closest'):
        return data['archived_snapshots']['closest']['url']
    return None
```

## Recommendations Summary

| Priority | Site | Action |
|----------|------|--------|
| 🟢 Done | YouTube | Implemented youtube-transcript-api fallback |
| 🟡 Future | Medium | Try cloudscraper or Archive.org fallback |
| 🔵 Accept | Twitter/X | Accept minimal content |
| 🔵 Accept | LinkedIn | Accept minimal content |
| 🔵 Accept | GitHub | Accept minimal content |

## Implementation Status

- [x] youtube-transcript-api added to ingest.py
- [ ] cloudscraper for Medium (future)
- [ ] Archive.org fallback (future)
- [ ] Rate limiting handling (future)
