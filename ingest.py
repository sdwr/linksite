"""
Link Discovery Game - Content Ingestion Module

Handles extracting content from various feed types:
- YouTube channels (via RSS)
- RSS/Atom feeds
- Reddit subreddits (via RSS)
- Bluesky accounts (via AT Protocol API)
- Websites (via trafilatura)

Each parser returns a list of dicts: {url, title, content, meta}
"""

import os
import re
from typing import Dict, Optional, List
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
import trafilatura
import feedparser
from sentence_transformers import SentenceTransformer

MAX_ITEMS_PER_FEED = 100


class ContentExtractor:
    """Handles content extraction from various URL types."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        youtube_patterns = [
            r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)',
            r'(https?://)?(www\.)?youtube\.com/shorts/'
        ]
        return any(re.search(pattern, url) for pattern in youtube_patterns)

    @staticmethod
    def is_youtube_channel_url(url: str) -> bool:
        patterns = [
            r'youtube\.com/(c|channel|user|@)[\w\-]+',
            r'youtube\.com/[\w\-]+$',
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def extract_youtube_content(self, url: str) -> Dict:
        try:
            video_id = self._extract_youtube_id(url)
            if not video_id:
                raise Exception("Could not extract YouTube video ID")
            invidious_url = f"https://inv.tux.pizza/api/v1/videos/{video_id}"
            response = requests.get(invidious_url, timeout=15)
            response.raise_for_status()
            data = response.json()
            return {
                'title': data.get('title', ''),
                'channel_name': data.get('author', ''),
                'transcript': data.get('description', ''),
                'thumbnail': data.get('videoThumbnails', [{}])[0].get('url', '') if data.get('videoThumbnails') else '',
                'type': 'youtube',
                'tags': data.get('keywords', [])
            }
        except Exception as e:
            raise Exception(f"Error extracting YouTube content: {str(e)}")

    @staticmethod
    def _extract_youtube_id(url: str) -> Optional[str]:
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([^&\n?#]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def extract_website_content(self, url: str) -> Dict:
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                raise Exception("Could not fetch URL")
            main_text = trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ''
            soup = BeautifulSoup(downloaded, 'html.parser')
            og_title = None
            og_image = None
            og_title_tag = soup.find('meta', property='og:title')
            if og_title_tag:
                og_title = og_title_tag.get('content')
            og_image_tag = soup.find('meta', property='og:image')
            if og_image_tag:
                og_image = og_image_tag.get('content')
            if not og_title:
                title_tag = soup.find('title')
                og_title = title_tag.string if title_tag else ''
            return {
                'title': og_title,
                'og_image': og_image,
                'main_text': main_text,
                'type': 'website'
            }
        except Exception as e:
            raise Exception(f"Error extracting website content: {str(e)}")


# â”€â”€â”€ Feed Parsers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def resolve_youtube_channel_id(channel_url: str) -> Optional[str]:
    """Fetch a YouTube channel page and extract the channel_id from canonical URL."""
    try:
        resp = requests.get(channel_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp.raise_for_status()
        # Best: canonical URL contains /channel/UCxxxxxx
        match = re.search(r'youtube\.com/channel/(UC[\w\-]+)', resp.text)
        if match:
            return match.group(1)
        # Fallback: channel_id= in link/meta tags
        match = re.search(r'channel_id=(UC[\w\-]+)', resp.text)
        if match:
            return match.group(1)
        # Fallback: meta tag
        soup = BeautifulSoup(resp.text, 'html.parser')
        meta = soup.find('meta', {'itemprop': 'channelId'})
        if meta:
            return meta.get('content')
        # Last resort: JSON channelId (less reliable, can match related channels)
        match = re.search(r'"externalId"\s*:\s*"(UC[\w\-]+)"', resp.text)
        if match:
            return match.group(1)
        return None
    except Exception:
        return None


def parse_youtube_channel(channel_url: str) -> List[Dict]:
    """Parse a YouTube channel via its RSS feed. Returns list of link dicts."""
    channel_id = resolve_youtube_channel_id(channel_url)
    if not channel_id:
        raise Exception(f"Could not resolve channel ID from {channel_url}")

    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    parsed = feedparser.parse(rss_url)

    if parsed.bozo and not parsed.entries:
        raise Exception(f"Failed to parse YouTube RSS: {parsed.bozo_exception}")

    channel_name = parsed.feed.get('title', 'Unknown Channel')
    items = []

    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        video_url = entry.get('link', '')
        if not video_url:
            continue

        # Get thumbnail from media:group
        thumbnail = ''
        if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            thumbnail = entry.media_thumbnail[0].get('url', '')

        items.append({
            'url': video_url,
            'title': entry.get('title', ''),
            'content': entry.get('summary', entry.get('title', '')),
            'meta': {
                'type': 'youtube',
                'channel_name': channel_name,
                'thumbnail': thumbnail,
                'published': entry.get('published', ''),
            }
        })

    return items


def parse_rss_feed(feed_url: str) -> List[Dict]:
    """Parse a generic RSS/Atom feed. Returns list of link dicts."""
    parsed = feedparser.parse(feed_url)

    if parsed.bozo and not parsed.entries:
        raise Exception(f"Failed to parse RSS: {parsed.bozo_exception}")

    items = []
    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        link = entry.get('link', '')
        if not link:
            continue

        summary = entry.get('summary', entry.get('description', ''))
        # Strip HTML tags from summary
        if summary:
            summary = re.sub(r'<[^>]+>', '', summary).strip()

        items.append({
            'url': link,
            'title': entry.get('title', ''),
            'content': summary,
            'meta': {
                'type': 'rss',
                'feed_title': parsed.feed.get('title', ''),
                'published': entry.get('published', ''),
                'author': entry.get('author', ''),
            }
        })

    return items


def normalize_reddit_url(url: str) -> str:
    """Convert a Reddit URL to its RSS equivalent."""
    url = url.rstrip('/')
    # If it's already an RSS URL, return as-is
    if url.endswith('.rss'):
        return url
    # Extract subreddit name from various formats
    match = re.search(r'(?:reddit\.com)?/?r/([\w]+)', url)
    if match:
        subreddit = match.group(1)
        return f"https://www.reddit.com/r/{subreddit}/hot/.rss"
    # Maybe it's just a subreddit name
    if re.match(r'^[\w]+$', url):
        return f"https://www.reddit.com/r/{url}/hot/.rss"
    return url + '/.rss'


def parse_reddit_feed(subreddit_url: str) -> List[Dict]:
    """Parse a Reddit subreddit via RSS. Returns list of link dicts."""
    rss_url = normalize_reddit_url(subreddit_url)

    # Reddit requires a custom User-Agent
    resp = requests.get(rss_url, timeout=15, headers={
        'User-Agent': 'LinkDiscovery/1.0 (feed aggregator)'
    })
    resp.raise_for_status()

    parsed = feedparser.parse(resp.text)

    if parsed.bozo and not parsed.entries:
        raise Exception(f"Failed to parse Reddit RSS: {parsed.bozo_exception}")

    items = []
    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        link = entry.get('link', '')
        if not link:
            continue

        summary = entry.get('summary', '')
        if summary:
            summary = re.sub(r'<[^>]+>', '', summary).strip()
            # Reddit summaries can be very long; truncate
            summary = summary[:2000]

        title = entry.get('title', '')

        items.append({
            'url': link,
            'title': title,
            'content': f"{title}. {summary}" if summary else title,
            'meta': {
                'type': 'reddit',
                'subreddit': parsed.feed.get('title', ''),
                'published': entry.get('published', ''),
                'author': entry.get('author', ''),
            }
        })

    return items


def parse_bluesky_feed(handle_or_url: str) -> List[Dict]:
    """Parse a Bluesky account's public feed via AT Protocol API."""
    # Extract handle from URL if needed
    handle = handle_or_url.strip()
    if 'bsky.app/profile/' in handle:
        match = re.search(r'bsky\.app/profile/([\w.\-]+)', handle)
        if match:
            handle = match.group(1)
    # Remove leading @
    handle = handle.lstrip('@')

    api_url = f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor={handle}&limit={MAX_ITEMS_PER_FEED}"
    resp = requests.get(api_url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    items = []
    for item in data.get('feed', []):
        post = item.get('post', {})
        record = post.get('record', {})
        text = record.get('text', '')
        author = post.get('author', {})
        uri = post.get('uri', '')

        # Build the bsky.app URL for this post
        # URI format: at://did:plc:xxx/app.bsky.feed.post/yyy
        post_url = ''
        if uri:
            parts = uri.split('/')
            if len(parts) >= 5:
                did = parts[2]
                rkey = parts[4]
                post_url = f"https://bsky.app/profile/{author.get('handle', did)}/post/{rkey}"

        if not post_url:
            continue

        # Check for embedded links
        embed = post.get('embed', {})
        external_url = ''
        external_title = ''
        if embed and embed.get('$type') == 'app.bsky.embed.external#view':
            external = embed.get('external', {})
            external_url = external.get('uri', '')
            external_title = external.get('title', '')

        # Prefer external link if present, otherwise use the post URL
        url = external_url or post_url
        title = external_title or (text[:100] + '...' if len(text) > 100 else text)
        content = text

        items.append({
            'url': url,
            'title': title,
            'content': content,
            'meta': {
                'type': 'bluesky',
                'author_handle': author.get('handle', ''),
                'author_name': author.get('displayName', ''),
                'post_url': post_url,
                'published': record.get('createdAt', ''),
            }
        })

    return items


# â”€â”€â”€ Legacy helpers (kept for compatibility) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def scrape_youtube(url: str) -> Dict:
    extractor = ContentExtractor()
    result = extractor.extract_youtube_content(url)
    return {
        'title': result['title'],
        'description': result['transcript'],
        'tags': result.get('tags', []),
        'channel': result['channel_name'],
        'thumbnail': result['thumbnail'],
        'type': 'youtube'
    }


def scrape_article(url: str) -> Dict:
    extractor = ContentExtractor()
    result = extractor.extract_website_content(url)
    return {
        'title': result['title'],
        'description': result['main_text'],
        'og_image': result['og_image'],
        'type': 'website'
    }


# â”€â”€â”€ Vectorization â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TextVectorizer:
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)

    def vectorize(self, text: str) -> List[float]:
        if not text or not text.strip():
            return [0.0] * 384
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()


_vectorizer = None


def vectorize(text: str) -> List[float]:
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = TextVectorizer()
    return _vectorizer.vectorize(text)
