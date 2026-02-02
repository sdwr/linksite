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

# Invidious instances to try in order (they can be flaky)
INVIDIOUS_INSTANCES = [
    "inv.tux.pizza",
    "vid.puffyan.us",
    "invidious.snopyta.org",
]

CONTENT_MAX_CHARS = 10000
DESCRIPTION_MAX_CHARS = 500


def _invidious_get(path: str, timeout: int = 15) -> requests.Response:
    """Try an Invidious API path across multiple instances, return first success."""
    last_error = None
    for instance in INVIDIOUS_INSTANCES:
        url = f"https://{instance}{path}"
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_error = e
            continue
    raise Exception(f"All Invidious instances failed for {path}: {last_error}")


def _parse_vtt_to_text(vtt_content: str) -> str:
    """
    Parse VTT/SRT caption content to plain text.
    Strips: WEBVTT header, timestamps (00:00:00.000 --> ...), numeric cue IDs, blank lines.
    Deduplicates consecutive identical lines (common in VTT).
    """
    lines = vtt_content.split("\n")
    text_lines = []
    prev_line = ""

    for line in lines:
        line = line.strip()

        # Skip WEBVTT header and metadata
        if line.startswith("WEBVTT"):
            continue
        if line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if line.startswith("NOTE"):
            continue

        # Skip timestamp lines (e.g., "00:00:01.234 --> 00:00:03.456")
        if re.match(r'\d{2}:\d{2}[:\.]?\d{0,2}[\.,]?\d{0,3}\s*-->', line):
            continue

        # Skip bare numeric lines (SRT cue identifiers)
        if re.match(r'^\d+$', line):
            continue

        # Skip blank lines
        if not line:
            continue

        # Strip inline VTT tags like <c>, </c>, <00:00:01.234>, etc.
        line = re.sub(r'<[^>]+>', '', line).strip()

        if not line:
            continue

        # Deduplicate consecutive identical lines
        if line != prev_line:
            text_lines.append(line)
            prev_line = line

    return " ".join(text_lines)


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
        """
        Extract YouTube video content using yt-dlp (primary) with oembed fallback.
        Returns: title, channel_name, description, content (captions), thumbnail, etc.
        """
        try:
            video_id = self._extract_youtube_id(url)
            if not video_id:
                raise Exception("Could not extract YouTube video ID")

            canonical_url = f"https://www.youtube.com/watch?v={video_id}"

            # --- Try yt-dlp first (best data) ---
            try:
                return self._extract_youtube_ytdlp(video_id, canonical_url)
            except Exception as yt_err:
                print(f"[Ingest] yt-dlp failed for {video_id}: {yt_err}")

            # --- Fallback: oEmbed (basic metadata only) ---
            try:
                return self._extract_youtube_oembed(video_id, canonical_url)
            except Exception as oe_err:
                print(f"[Ingest] oEmbed failed for {video_id}: {oe_err}")

            raise Exception("All YouTube extraction methods failed")

        except Exception as e:
            raise Exception(f"Error extracting YouTube content: {str(e)}")

    def _extract_youtube_ytdlp(self, video_id: str, url: str) -> Dict:
        """Extract YouTube metadata + captions via yt-dlp."""
        import subprocess, json, tempfile, os

        # Get metadata
        result = subprocess.run(
            ['yt-dlp', '--dump-json', '--no-download', '--no-warnings', url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise Exception(f"yt-dlp metadata failed: {result.stderr[:200]}")

        data = json.loads(result.stdout)
        title = data.get('title', '')
        channel_name = data.get('channel', data.get('uploader', ''))
        description = data.get('description', '')
        duration = data.get('duration', 0)
        view_count = data.get('view_count', 0)
        tags = data.get('tags', []) or []

        # Best thumbnail
        thumbnail = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

        # --- Try to get captions ---
        captions_text = ''
        has_captions = False
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                sub_path = os.path.join(tmpdir, 'subs')
                sub_result = subprocess.run(
                    ['yt-dlp', '--write-auto-sub', '--write-sub', '--sub-lang', 'en',
                     '--sub-format', 'vtt', '--skip-download', '--no-warnings',
                     '-o', sub_path, url],
                    capture_output=True, text=True, timeout=60
                )
                # Find the subtitle file
                for f in os.listdir(tmpdir):
                    if f.endswith('.vtt'):
                        vtt_path = os.path.join(tmpdir, f)
                        with open(vtt_path, 'r', encoding='utf-8') as vf:
                            raw = vf.read()
                        captions_text = _parse_vtt_to_text(raw)
                        has_captions = bool(captions_text.strip())
                        break
        except Exception as cap_err:
            print(f"[Ingest] yt-dlp captions failed for {video_id}: {cap_err}")

        short_description = description[:DESCRIPTION_MAX_CHARS] if description else ''
        full_content = ''
        if captions_text:
            full_content = captions_text[:CONTENT_MAX_CHARS]
        elif description:
            full_content = description[:CONTENT_MAX_CHARS]

        meta = {
            'type': 'youtube',
            'channel_name': channel_name,
            'duration': duration,
            'view_count': view_count,
            'has_captions': has_captions,
        }

        return {
            'title': title,
            'channel_name': channel_name,
            'description': short_description,
            'content': full_content,
            'thumbnail': thumbnail,
            'type': 'youtube',
            'tags': tags[:20],
            'duration': duration,
            'view_count': view_count,
            'has_captions': has_captions,
            'meta': meta,
            'transcript': description,
        }

    def _extract_youtube_oembed(self, video_id: str, url: str) -> Dict:
        """Lightweight fallback: just title, channel, thumbnail via oEmbed."""
        import requests as req
        resp = req.get(
            f"https://www.youtube.com/oembed?url={url}&format=json",
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        title = data.get('title', '')
        channel_name = data.get('author_name', '')
        thumbnail = data.get('thumbnail_url', f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")

        return {
            'title': title,
            'channel_name': channel_name,
            'description': title,
            'content': '',
            'thumbnail': thumbnail,
            'type': 'youtube',
            'tags': [],
            'duration': 0,
            'view_count': 0,
            'has_captions': False,
            'meta': {'type': 'youtube', 'channel_name': channel_name, 'has_captions': False},
            'transcript': '',
        }

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
        """
        Extract website/article content via trafilatura with enhanced metadata.

        Returns:
            title, og_image, description (short ~500 chars), content (full ~10000 chars),
            main_text (legacy), type, meta (author, date, sitename)
        """
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                raise Exception("Could not fetch URL")

            # Extract full text content
            main_text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False
            ) or ''

            # Extract metadata via trafilatura
            author = None
            date = None
            sitename = None
            try:
                metadata = trafilatura.extract_metadata(downloaded)
                if metadata:
                    author = metadata.author if hasattr(metadata, 'author') else None
                    date = metadata.date if hasattr(metadata, 'date') else None
                    sitename = metadata.sitename if hasattr(metadata, 'sitename') else None
            except Exception as meta_err:
                print(f"[Ingest] Metadata extraction error for {url}: {meta_err}")

            # Parse HTML for OG tags (same as before)
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

            # Fallback sitename from OG
            if not sitename:
                og_site_tag = soup.find('meta', property='og:site_name')
                if og_site_tag:
                    sitename = og_site_tag.get('content')

            # Build short description and full content
            short_description = main_text[:DESCRIPTION_MAX_CHARS] if main_text else ''
            full_content = main_text[:CONTENT_MAX_CHARS] if main_text else ''

            meta = {
                'type': 'website',
            }
            if author:
                meta['author'] = author
            if date:
                meta['date'] = date
            if sitename:
                meta['sitename'] = sitename

            return {
                'title': og_title,
                'og_image': og_image,
                'description': short_description,
                'content': full_content,
                'main_text': main_text,  # Legacy compat
                'type': 'website',
                'meta': meta,
            }
        except Exception as e:
            raise Exception(f"Error extracting website content: {str(e)}")


# ——— Feed Parsers ———————————————————————————————————————————

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


# ——— Legacy helpers (kept for compatibility) ————————————————

def scrape_youtube(url: str) -> Dict:
    extractor = ContentExtractor()
    result = extractor.extract_youtube_content(url)
    return {
        'title': result['title'],
        'description': result['transcript'],  # Legacy: returns video description
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
        'description': result['main_text'],  # Legacy: returns full main_text
        'og_image': result['og_image'],
        'type': 'website'
    }


# ——— Vectorization ——————————————————————————————————————————

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
