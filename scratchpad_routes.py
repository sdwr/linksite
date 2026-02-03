"""
Scratchpad HTML pages for Linksite.
API routes are in scratchpad_api.py — this file handles /add, /browse, /link/{id}.
"""

import os
import re
import asyncio
import httpx
import json as _json
from typing import Optional, List
from urllib.parse import urlparse
from datetime import datetime, timezone
from fastapi import BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from scratchpad_api import get_external_discussions, fetch_and_save_external_discussions, check_reverse_lookup


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def get_base_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split('/')[0]
    except Exception:
        return ""


def time_ago(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        secs = diff.total_seconds()
        if secs < 60: return "just now"
        if secs < 3600: return f"{int(secs//60)}m ago"
        if secs < 86400: return f"{int(secs//3600)}h ago"
        return f"{int(secs//86400)}d ago"
    except:
        return ""


def normalize_url(url: str) -> str:
    """Normalize a URL: add https://, strip www, strip trailing slash, lowercase host."""
    url = url.strip()
    if not url:
        return url
    # Lowercase the scheme for comparison
    url_lower = url.lower()
    # Add scheme if missing
    if not url_lower.startswith(('http://', 'https://')):
        url = 'https://' + url
    # Normalize http -> https
    elif url_lower.startswith('http://'):
        url = 'https://' + url[7:]
    parsed = urlparse(url)
    # Lowercase and strip www from host
    host = (parsed.netloc or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    # Strip trailing slash from path (but keep non-empty paths)
    path = parsed.path
    if path == '/':
        path = ''
    elif path.endswith('/'):
        path = path.rstrip('/')
    # Rebuild URL
    result = 'https://' + host + path
    if parsed.query:
        result += '?' + parsed.query
    if parsed.fragment:
        result += '#' + parsed.fragment
    return result


def extract_youtube_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats. Returns empty string if not YouTube."""
    if not url:
        return ""
    m = re.search(
        r'(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
        url
    )
    return m.group(1) if m else ""


def is_bluesky_url(url: str) -> bool:
    """Check if URL is a Bluesky post."""
    return bool(url and 'bsky.app/profile/' in url and '/post/' in url)


def get_or_create_tag(supabase, slug: str) -> dict:
    slug = slug.strip().lower().replace(' ', '-')
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    if not slug:
        return None
    existing = supabase.table('tags').select('*').eq('slug', slug).execute()
    if existing.data:
        return existing.data[0]
    name = slug.replace('-', ' ').title()
    result = supabase.table('tags').insert({'name': name, 'slug': slug, 'score': 0}).execute()
    return result.data[0] if result.data else None


DARK_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f172a; color: #e2e8f0; line-height: 1.6;
}
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; color: #93bbfc; }

/* Top bar */
.topbar {
    background: #1e293b; border-bottom: 1px solid #334155;
    padding: 12px 24px; display: flex; gap: 24px; align-items: center;
}
.topbar .brand { color: #38bdf8; font-size: 18px; font-weight: 700; margin-right: auto; text-decoration: none; }
.topbar a { color: #94a3b8; font-weight: 500; font-size: 14px; }
.topbar a:hover { color: #e2e8f0; text-decoration: none; }

/* Layout */
.container { max-width: 900px; margin: 24px auto; padding: 0 16px; }
.card {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 12px; padding: 24px; margin-bottom: 20px;
}
h1 { font-size: 24px; margin-bottom: 16px; color: #f1f5f9; }
h2 { font-size: 18px; margin-bottom: 12px; color: #e2e8f0; }

/* Tags */
.pill {
    display: inline-flex; align-items: center; gap: 4px;
    background: #312e81; color: #a5b4fc;
    padding: 4px 12px; border-radius: 14px;
    font-size: 13px; margin: 3px 4px 3px 0; font-weight: 500;
}
.pill .x {
    color: #818cf8; cursor: pointer; font-weight: 700;
    text-decoration: none; font-size: 14px; line-height: 1;
}
.pill .x:hover { color: #f87171; }
.tags-row {
    display: flex; flex-wrap: wrap; align-items: center; gap: 0;
}
.tag-add-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; border-radius: 14px;
    background: #1e1b4b; border: 1px dashed #4338ca;
    color: #818cf8; font-size: 18px; font-weight: 600;
    cursor: pointer; text-decoration: none; margin: 3px 0;
    transition: background 0.15s;
}
.tag-add-btn:hover { background: #312e81; color: #a5b4fc; text-decoration: none; }
.tag-form {
    display: none; align-items: center; gap: 6px; margin: 3px 0;
}
.tag-form.show { display: inline-flex; }
.tag-form input {
    width: 120px; padding: 4px 10px; background: #0f172a;
    border: 1px solid #4338ca; border-radius: 14px;
    color: #e2e8f0; font-size: 13px;
}
.tag-form input:focus { outline: none; border-color: #60a5fa; }
.tag-form button {
    background: #312e81; border: none; color: #a5b4fc;
    padding: 4px 10px; border-radius: 14px; font-size: 13px;
    cursor: pointer; font-weight: 600;
}

/* Images */
.img-preview {
    max-width: 100%; max-height: 300px; border-radius: 8px;
    margin: 12px 0; object-fit: cover;
}

/* YouTube embed responsive container */
.yt-embed-wrap {
    position: relative; width: 100%; padding-bottom: 56.25%;
    margin: 12px 0; border-radius: 8px; overflow: hidden;
    background: #000;
}
.yt-embed-wrap iframe {
    position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none;
}

/* Bluesky embed container */
.bsky-embed-wrap {
    margin: 12px 0; border-radius: 8px; overflow: hidden;
    background: #1e293b; min-height: 80px;
}

/* Comments (reddit-style) */
.comment-input {
    display: flex; gap: 10px; margin-bottom: 20px;
}
.comment-input textarea {
    flex: 1; padding: 10px 14px; background: #0f172a;
    border: 1px solid #334155; border-radius: 8px;
    color: #e2e8f0; font-size: 14px; font-family: inherit;
    min-height: 44px; max-height: 120px; resize: vertical;
}
.comment-input textarea:focus { outline: none; border-color: #60a5fa; }
.comment-input button {
    align-self: flex-end; padding: 10px 18px; background: #2563eb;
    border: none; border-radius: 8px; color: #fff;
    font-weight: 600; font-size: 14px; cursor: pointer;
    white-space: nowrap;
}
.comment-input button:hover { background: #1d4ed8; }

.comment {
    display: flex; gap: 10px; padding: 10px 0;
    border-bottom: 1px solid #1e293b;
}
.comment:last-child { border-bottom: none; }
.vote-col {
    display: flex; flex-direction: column; align-items: center;
    gap: 0; min-width: 32px; padding-top: 2px;
}
.vote-btn {
    background: none; border: none; cursor: pointer;
    color: #475569; font-size: 16px; padding: 2px 4px; line-height: 1;
    transition: color 0.15s;
}
.vote-btn:hover { color: #60a5fa; }
.vote-btn.up:hover { color: #f97316; }
.vote-btn.down:hover { color: #8b5cf6; }
.vote-score {
    font-size: 12px; font-weight: 700; color: #64748b; line-height: 1;
}
.comment-body { flex: 1; min-width: 0; }
.comment-meta { font-size: 12px; color: #64748b; margin-bottom: 4px; }
.comment-meta strong { color: #94a3b8; font-weight: 600; }
.comment-text { font-size: 14px; color: #cbd5e1; white-space: pre-wrap; word-break: break-word; }

/* Related links */
.related-link {
    display: block; padding: 8px 12px;
    border: 1px solid #334155; border-radius: 8px;
    margin-bottom: 6px; background: #0f172a;
}
.related-link:hover { background: #1e293b; border-color: #475569; text-decoration: none; }
.related-link .r-title { color: #e2e8f0; font-weight: 500; }
.related-link .r-url { color: #64748b; font-size: 12px; }

/* Forms */
input[type="text"], input[type="url"], textarea, select {
    width: 100%; padding: 10px 14px; background: #0f172a;
    border: 1px solid #334155; border-radius: 8px;
    color: #e2e8f0; font-size: 14px; margin-bottom: 10px; font-family: inherit;
}
input:focus, textarea:focus { outline: none; border-color: #60a5fa; }
textarea { min-height: 80px; resize: vertical; }

.btn {
    display: inline-block; cursor: pointer; padding: 10px 20px;
    border-radius: 8px; border: none;
    font-size: 14px; font-weight: 600; text-align: center;
}
.btn-primary { background: #2563eb; color: #fff; }
.btn-primary:hover { background: #1d4ed8; text-decoration: none; }
.btn-sm { padding: 6px 14px; font-size: 13px; }
.btn-ghost { background: transparent; border: 1px solid #475569; color: #94a3b8; }
.btn-ghost:hover { background: #1e293b; color: #e2e8f0; }
label { display: block; font-size: 13px; color: #94a3b8; margin-bottom: 4px; font-weight: 500; }

.msg-ok {
    background: #064e3b; color: #6ee7b7; padding: 12px 16px;
    border-radius: 8px; margin-bottom: 16px; border: 1px solid #065f46;
}
.msg-err {
    background: #450a0a; color: #fca5a5; padding: 12px 16px;
    border-radius: 8px; margin-bottom: 16px; border: 1px solid #7f1d1d;
}

/* Browse grid */
.grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 16px;
}
.link-card {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 12px; overflow: hidden;
    transition: border-color 0.2s; display: block;
}
.link-card:hover { border-color: #475569; text-decoration: none; }
.link-card .thumb {
    width: 100%; height: 160px; object-fit: cover;
    background: #0f172a; display: block;
}
.link-card .thumb-placeholder {
    width: 100%; height: 160px;
    background: linear-gradient(135deg, #1e293b, #0f172a);
    display: flex; align-items: center; justify-content: center;
    color: #334155; font-size: 40px;
}
.link-card .body { padding: 14px; }
.link-card .card-title {
    color: #f1f5f9; font-weight: 600; font-size: 15px;
    line-height: 1.3; margin-bottom: 4px;
    display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden;
}
.link-card .card-domain { color: #64748b; font-size: 12px; margin-bottom: 8px; }
.link-card .card-pills { margin-bottom: 6px; }
.link-card .card-meta {
    color: #475569; font-size: 12px;
    display: flex; justify-content: space-between;
}
.sort-bar {
    display: flex; gap: 8px; margin-bottom: 16px;
    align-items: center; flex-wrap: wrap;
}
.sort-bar a {
    padding: 6px 14px; border-radius: 20px; font-size: 13px;
    background: #1e293b; color: #94a3b8;
    border: 1px solid #334155; text-decoration: none;
}
.sort-bar a:hover { color: #e2e8f0; border-color: #475569; }
.sort-bar a.active { background: #2563eb; color: #fff; border-color: #2563eb; }
.search-box form { display: flex; gap: 8px; width: 100%; margin-bottom: 16px; }
.search-box input { flex: 1; margin-bottom: 0; }

/* Check Link page */
.check-link-form {
    display: flex; gap: 10px; align-items: center;
}
.check-link-form input {
    flex: 1; margin-bottom: 0; padding: 14px 18px; font-size: 16px;
    border-radius: 12px;
}
.check-link-form button {
    padding: 14px 28px; font-size: 16px; border-radius: 12px;
    white-space: nowrap;
}

.empty-state {
    text-align: center; padding: 60px 20px; color: #475569;
}
.empty-state .icon { font-size: 48px; margin-bottom: 12px; }


/* External Discussions */
.ext-disc {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 14px; border: 1px solid #334155;
    border-radius: 8px; margin-bottom: 8px;
    background: #0f172a; transition: border-color 0.2s;
}
.ext-disc:hover { border-color: #475569; }
.ext-disc .platform-icon {
    font-size: 20px; min-width: 28px; text-align: center;
}
.ext-disc .disc-info { flex: 1; min-width: 0; }
.ext-disc .disc-title {
    color: #e2e8f0; font-weight: 500; font-size: 14px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ext-disc .disc-meta {
    color: #64748b; font-size: 12px; margin-top: 2px;
}
.ext-disc .disc-stats {
    display: flex; gap: 12px; align-items: center;
    color: #94a3b8; font-size: 13px; font-weight: 500;
    white-space: nowrap;
}
.ext-disc .disc-stats span { display: flex; align-items: center; gap: 4px; }
.refresh-btn {
    display: inline-flex; align-items: center; gap: 6px;
    background: none; border: 1px solid #334155; border-radius: 6px;
    padding: 4px 12px; color: #64748b; font-size: 12px;
    cursor: pointer; transition: all 0.15s;
}
.refresh-btn:hover { border-color: #60a5fa; color: #60a5fa; text-decoration: none; }
/* Small pill for cards */
.pill-sm {
    display: inline-block; background: #312e81; color: #a5b4fc;
    padding: 2px 8px; border-radius: 10px; font-size: 11px;
    margin: 1px 2px; font-weight: 500;
}

/* Star button */
.star-btn {
    display: inline-flex; align-items: center; gap: 6px;
    background: none; border: 1px solid #334155; border-radius: 8px;
    padding: 6px 14px; cursor: pointer; color: #94a3b8;
    font-size: 14px; transition: all 0.15s;
}
.star-btn:hover { border-color: #eab308; color: #eab308; background: rgba(234,179,8,0.08); }
.star-btn .star-icon { font-size: 18px; }
.star-btn .star-count { font-weight: 600; }

/* Loading spinner */
.page-loader {
    position: fixed; top: 0; left: 0; right: 0; height: 3px;
    background: transparent; z-index: 9999; pointer-events: none;
}
.page-loader .bar {
    height: 100%; width: 0; background: #2563eb;
    transition: width 0.3s ease;
}
.page-loader.loading .bar { width: 70%; transition: width 8s ease-out; }
.page-loader.done .bar { width: 100%; transition: width 0.15s ease; opacity: 0; transition: width 0.15s, opacity 0.3s 0.2s; }

/* Lazy loading spinner */
.lazy-loader {
    display: flex; align-items: center; justify-content: center;
    padding: 32px; color: #64748b; font-size: 14px; gap: 12px;
}
.lazy-loader::before {
    content: ''; display: block; width: 22px; height: 22px;
    border: 2.5px solid #334155; border-top-color: #60a5fa;
    border-radius: 50%; animation: lazysp 0.7s linear infinite;
    flex-shrink: 0;
}
@keyframes lazysp { to { transform: rotate(360deg); } }

/* Skeleton card for browse grid */
.skeleton-card {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 12px; overflow: hidden;
}
.skeleton-card .skel-thumb {
    width: 100%; height: 160px;
    background: linear-gradient(90deg, #1e293b 25%, #283548 50%, #1e293b 75%);
    background-size: 200% 100%; animation: shimmer 1.5s infinite;
}
.skeleton-card .skel-body { padding: 14px; }
.skeleton-card .skel-line {
    height: 14px; border-radius: 4px; margin-bottom: 10px;
    background: linear-gradient(90deg, #1e293b 25%, #283548 50%, #1e293b 75%);
    background-size: 200% 100%; animation: shimmer 1.5s infinite;
}
.skeleton-card .skel-line.w75 { width: 75%; }
.skeleton-card .skel-line.w50 { width: 50%; }
.skeleton-card .skel-line.w30 { width: 30%; }
@keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}
/* User badge in topbar */
.user-badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: #312e81; color: #a5b4fc; padding: 4px 12px;
    border-radius: 14px; font-size: 13px; font-weight: 500;
    white-space: nowrap;
}
/* Commenting-as label */
.commenting-as {
    font-size: 12px; color: #64748b; margin-bottom: 6px;
}
.commenting-as strong { color: #a5b4fc; }

/* Reddit Embeds */
.reddit-embed-wrap {
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 12px;
}
.reddit-embed-wrap blockquote {
    margin: 0 !important;
    border: 1px solid #334155 !important;
    border-radius: 8px;
}
.reddit-embed-wrap iframe {
    border-radius: 8px !important;
}
"""


def dark_nav():
    return """<div class="topbar">
        <a href="/browse" class="brand">&#128279; Linksite</a>
        <a href="/browse">Browse</a>
        <a href="/add">Check Link</a>
        <span id="user-badge" class="user-badge" style="display:none"></span>
    </div>"""


def dark_page(title, body, extra_scripts=""):
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Linksite</title><style>{DARK_CSS}</style></head><body>
<div class="page-loader" id="loader"><div class="bar"></div></div>
{dark_nav()}<div class="container">{body}</div>
<script>
document.addEventListener('click', function(e) {{
    var a = e.target.closest('a[href]');
    if (a && a.href && !a.href.startsWith('javascript') && !a.target && a.origin === location.origin) {{
        document.getElementById('loader').className = 'page-loader loading';
    }}
}});
document.querySelectorAll('form').forEach(function(f) {{
    f.addEventListener('submit', function() {{
        document.getElementById('loader').className = 'page-loader loading';
    }});
}});
</script>
{extra_scripts}
</body></html>"""


# --- Async PostgREST helper for parallel queries ---
_SUPABASE_URL = None
_SUPABASE_HEADERS = None

def _init_async_client():
    """Initialize the async PostgREST config from environment."""
    global _SUPABASE_URL, _SUPABASE_HEADERS
    url = os.environ.get('SUPABASE_URL', '')
    key = os.environ.get('SUPABASE_KEY', '')
    _SUPABASE_URL = url.rstrip('/') + '/rest/v1'
    _SUPABASE_HEADERS = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }

async def _pg_get(table, select='*', params=None):
    """Async PostgREST GET query. Returns list of dicts."""
    if _SUPABASE_URL is None:
        _init_async_client()
    url = f'{_SUPABASE_URL}/{table}'
    qp = {'select': select}
    if params:
        qp.update(params)
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=_SUPABASE_HEADERS, params=qp, timeout=10)
        r.raise_for_status()
        return r.json()


# --- Shared JS helpers (used by both detail and browse pages) ---
_JS_HELPERS = """
function _esc(s){var d=document.createElement('div');d.textContent=s||'';return d.innerHTML;}
function _domain(u){try{return new URL(u).hostname;}catch(e){return '';}}
function _ago(dt){
    if(!dt)return '';
    try{var d=new Date(dt);var s=(Date.now()-d.getTime())/1000;
    if(s<60)return 'just now';if(s<3600)return Math.floor(s/60)+'m ago';
    if(s<86400)return Math.floor(s/3600)+'h ago';return Math.floor(s/86400)+'d ago';
    }catch(e){return '';}
}
var _cachedRandomUrl=null;
function _preloadRandom(){
    fetch('/api/random?format=json').then(function(r){return r.json();})
    .then(function(d){_cachedRandomUrl=d.url||null;}).catch(function(){});
}
_preloadRandom();
document.addEventListener('click',function(e){
    var a=e.target.closest('a[href*="/api/random"]');
    if(a&&_cachedRandomUrl){e.preventDefault();var u=_cachedRandomUrl;_cachedRandomUrl=null;
    document.getElementById('loader').className='page-loader loading';window.location.href=u;_preloadRandom();}
});

// --- User badge + commenting-as ---
fetch('/api/me').then(function(r){return r.json();}).then(function(d){
    if(d&&d.display_name){
        var b=document.getElementById('user-badge');
        if(b){b.innerHTML='&#128100; '+_esc(d.display_name);b.style.display='';}
        var ca=document.getElementById('commenting-as');
        if(ca){ca.innerHTML='Commenting as <strong>'+_esc(d.display_name)+'</strong>';}
        var ai=document.getElementById('comment-author');
        if(ai){ai.value=d.display_name;}
    }
}).catch(function(){});
"""


def register_scratchpad_routes(app, supabase, vectorize_fn):
    """Register all HTML page routes on the FastAPI app."""

    from ingest import ContentExtractor

    async def _ingest_link_content(link_id, url):
        try:
            extractor = ContentExtractor()
            if extractor.is_youtube_url(url):
                data = extractor.extract_youtube_content(url)
                update = {
                    'title': data.get('title', ''),
                    'description': data.get('transcript', '')[:5000],
                    'og_image_url': data.get('thumbnail', ''),
                    'source': 'youtube',
                }
                text_for_vector = f"{data.get('title', '')}. {data.get('transcript', '')}"
            elif is_bluesky_url(url):
                # Bluesky post — try oEmbed for metadata + thumbnail
                update = {'source': 'bluesky'}
                text_for_vector = ''
                try:
                    import httpx as _hx
                    async with _hx.AsyncClient() as client:
                        oembed_resp = await client.get(
                            'https://embed.bsky.app/oembed',
                            params={'url': url, 'format': 'json'},
                            timeout=10
                        )
                        if oembed_resp.status_code == 200:
                            oembed = oembed_resp.json()
                            if oembed.get('author_name'):
                                update['title'] = f"Post by {oembed['author_name']}"
                                text_for_vector = f"Bluesky post by {oembed['author_name']}."
                            # Try to extract thumbnail from oEmbed HTML
                            html_str = oembed.get('html', '')
                            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_str)
                            if img_match:
                                update['og_image_url'] = img_match.group(1)
                except Exception as e:
                    print(f"[Ingest] Bluesky oEmbed failed for {url}: {e}")
                # Also try the AT Protocol public API for richer data
                try:
                    import httpx as _hx
                    # Parse handle and rkey from URL
                    bsky_match = re.search(r'bsky\.app/profile/([^/]+)/post/([^/?#]+)', url)
                    if bsky_match:
                        handle, rkey = bsky_match.group(1), bsky_match.group(2)
                        async with _hx.AsyncClient() as client:
                            # Resolve handle to DID if needed
                            if not handle.startswith('did:'):
                                resolve = await client.get(
                                    f'https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle',
                                    params={'handle': handle}, timeout=10
                                )
                                if resolve.status_code == 200:
                                    did = resolve.json().get('did', '')
                                else:
                                    did = handle
                            else:
                                did = handle
                            # Fetch the post
                            post_resp = await client.get(
                                'https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread',
                                params={'uri': f'at://{did}/app.bsky.feed.post/{rkey}', 'depth': 0},
                                timeout=10
                            )
                            if post_resp.status_code == 200:
                                thread = post_resp.json()
                                post = thread.get('thread', {}).get('post', {})
                                record = post.get('record', {})
                                author = post.get('author', {})
                                post_text = record.get('text', '')
                                display_name = author.get('displayName', author.get('handle', ''))
                                if post_text:
                                    update['description'] = post_text[:5000]
                                    text_for_vector = f"Bluesky post by {display_name}: {post_text}"
                                if display_name and not update.get('title'):
                                    update['title'] = f"Post by {display_name}"
                                # Thumbnail: prefer embed image > author avatar
                                embed = post.get('embed', {})
                                embed_images = embed.get('images', [])
                                if embed_images and not update.get('og_image_url'):
                                    update['og_image_url'] = embed_images[0].get('fullsize', '') or embed_images[0].get('thumb', '')
                                elif embed.get('external', {}).get('thumb') and not update.get('og_image_url'):
                                    update['og_image_url'] = embed['external']['thumb']
                                elif author.get('avatar') and not update.get('og_image_url'):
                                    update['og_image_url'] = author['avatar']
                except Exception as e:
                    print(f"[Ingest] Bluesky AT Proto failed for {url}: {e}")
                data = update  # for consistency
            else:
                data = extractor.extract_website_content(url)
                update = {
                    'title': data.get('title', ''),
                    'description': (data.get('main_text', '') or '')[:5000],
                    'og_image_url': data.get('og_image', ''),
                    'source': 'website',
                }
                text_for_vector = f"{data.get('title', '')}. {data.get('main_text', '')}"

            existing = supabase.table('links').select('title, description').eq('id', link_id).execute()
            if existing.data:
                ex = existing.data[0]
                if ex.get('title'):
                    update.pop('title', None)
                if ex.get('description'):
                    update.pop('description', None)

            try:
                vec = vectorize_fn(text_for_vector[:5000])
                update['content_vector'] = vec
            except Exception as e:
                print(f"Vectorization failed for link {link_id}: {e}")

            supabase.table('links').update(update).eq('id', link_id).execute()
            print(f"[Ingest] Link {link_id} enriched from {url}")
        except Exception as e:
            print(f"[Ingest] Error processing link {link_id}: {e}")

    async def _ensure_parent_site(url, link_id):
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or '').lower()
            if host.startswith('www.'):
                host = host[4:]
            if not host:
                return
            # Don't create parent for root domains
            path = parsed.path.rstrip('/')
            if not path and not parsed.query:
                return
            base_url = 'https://' + host
            existing = supabase.table('links').select('id').eq('url', base_url).execute()
            if existing.data:
                parent_id = existing.data[0]['id']
            else:
                result = supabase.table('links').insert({
                    'url': base_url,
                    'title': host,
                    'source': 'auto-parent',
                }).execute()
                parent_id = result.data[0]['id'] if result.data else None
            if parent_id and parent_id != link_id:
                supabase.table('links').update({'parent_link_id': parent_id}).eq('id', link_id).execute()
        except Exception as e:
            print(f"[Parent] Error for {url}: {e}")

    def _enrich(link: dict) -> dict:
        """Add tags, notes, related to a link dict."""
        lid = link['id']
        # Tags
        lt_resp = supabase.table('link_tags').select('tag_id').eq('link_id', lid).execute()
        tag_ids = [lt['tag_id'] for lt in (lt_resp.data or [])]
        if tag_ids:
            tags_resp = supabase.table('tags').select('id, name, slug').in_('id', tag_ids).execute()
            link['tags'] = tags_resp.data or []
        else:
            link['tags'] = []
        # Notes
        notes_resp = supabase.table('notes').select('*').eq('link_id', lid).order('created_at', desc=True).execute()
        link['notes'] = notes_resp.data or []
        link['note_count'] = len(link['notes'])
        # Parent
        if link.get('parent_link_id'):
            pr = supabase.table('links').select('id, url, title').eq('id', link['parent_link_id']).execute()
            link['parent'] = pr.data[0] if pr.data else None
        else:
            link['parent'] = None
        return link

    def _find_related(link_id: int, limit: int = 6) -> list:
        """Find related links (by parent or recent)."""
        try:
            link_resp = supabase.table('links').select('parent_link_id, feed_id').eq('id', link_id).execute()
            if not link_resp.data:
                return []
            ld = link_resp.data[0]
            related = []
            if ld.get('parent_link_id'):
                r = supabase.table('links').select('id, url, title, og_image_url').eq(
                    'parent_link_id', ld['parent_link_id']
                ).neq('id', link_id).limit(limit).execute()
                related.extend(r.data or [])
            if ld.get('feed_id') and len(related) < limit:
                r = supabase.table('links').select('id, url, title, og_image_url').eq(
                    'feed_id', ld['feed_id']
                ).neq('id', link_id).limit(limit - len(related)).execute()
                seen = {x['id'] for x in related}
                related.extend(x for x in (r.data or []) if x['id'] not in seen)
            if len(related) < limit:
                r = supabase.table('links').select('id, url, title, og_image_url').neq(
                    'id', link_id
                ).neq('source', 'auto-parent').order('created_at', desc=True).limit(limit - len(related)).execute()
                seen = {x['id'] for x in related}
                related.extend(x for x in (r.data or []) if x['id'] not in seen)
            return related[:limit]
        except Exception as e:
            print(f"Error finding related: {e}")
            return []

    async def _fetch_discussions_bg(link_id, url):
        """Background task to fetch external discussions + reverse lookup."""
        import threading
        def _run():
            fetch_and_save_external_discussions(link_id, url)
            check_reverse_lookup(url, link_id)
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # ========== GET /add — Check Link page ==========
    @app.get("/add", response_class=HTMLResponse)
    async def page_add_link(message: Optional[str] = None, error: Optional[str] = None):
        msgs = ""
        if message:
            msgs += f'<div class="msg-ok">{_esc(message)}</div>'
        if error:
            msgs += f'<div class="msg-err">{_esc(error)}</div>'
        body = f"""{msgs}
        <div style="padding: 40px 0 20px; text-align: center;">
            <h1 style="font-size: 32px; margin-bottom: 8px;">Check a Link</h1>
            <p style="color: #64748b; margin-bottom: 32px;">Paste a URL to save it, extract info, and start a discussion.</p>
        </div>
        <div class="card">
            <form method="POST" action="/add" class="check-link-form">
                <input type="text" name="url" placeholder="example.com or https://..." required autofocus>
                <button type="submit" class="btn btn-primary">Check Link</button>
            </form>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="/browse" style="color: #64748b; font-size: 14px;">or browse existing links &rarr;</a>
        </div>"""
        return HTMLResponse(dark_page("Check Link", body))

    # ========== POST /add ==========
    @app.post("/add", response_class=HTMLResponse)
    async def page_add_link_post(
        background_tasks: BackgroundTasks,
        url: str = Form(...),
    ):
        url = normalize_url(url)
        if not url:
            return RedirectResponse(url="/add?error=URL+is+required", status_code=303)

        existing = supabase.table('links').select('id').eq('url', url).execute()
        if existing.data:
            link_id = existing.data[0]['id']
            return RedirectResponse(url=f"/link/{link_id}", status_code=303)

        insert_data = {
            'url': url,
            'title': '',
            'description': '',
            'submitted_by': 'web',
            'source': 'scratchpad',
        }
        result = supabase.table('links').insert(insert_data).execute()
        if not result.data:
            return RedirectResponse(url="/add?error=Failed+to+create+link", status_code=303)
        link_id = result.data[0]['id']

        background_tasks.add_task(_ingest_link_content, link_id, url)
        background_tasks.add_task(_ensure_parent_site, url, link_id)
        background_tasks.add_task(_fetch_discussions_bg, link_id, url)
        return RedirectResponse(url=f"/link/{link_id}", status_code=303)

    # ========== GET /link/{id} — Detail page (lazy-loaded sections) ==========
    @app.get("/link/{link_id}", response_class=HTMLResponse)
    async def page_link_detail(link_id: int, message: Optional[str] = None, error: Optional[str] = None):
        resp = supabase.table('links').select('*').eq('id', link_id).execute()
        if not resp.data:
            return HTMLResponse(dark_page("Not Found", '<div class="msg-err">Link not found.</div>'))

        link = resp.data[0]
        lid = link['id']

        # --- Only fetch tags and parent server-side (they're small) ---
        async def _fetch_tags():
            lt_data = await _pg_get('link_tags', 'tag_id', {'link_id': f'eq.{lid}'})
            tag_ids = [lt['tag_id'] for lt in lt_data]
            if tag_ids:
                ids_str = ','.join(str(i) for i in tag_ids)
                return await _pg_get('tags', 'id,name,slug', {'id': f'in.({ids_str})'})
            return []

        async def _fetch_parent():
            pid = link.get('parent_link_id')
            if pid:
                data = await _pg_get('links', 'id,url,title', {'id': f'eq.{pid}'})
                return data[0] if data else None
            return None

        tags, parent = await asyncio.gather(
            _fetch_tags(),
            _fetch_parent(),
        )

        link['tags'] = tags
        link['parent'] = parent

        msgs = ""
        if message:
            msgs += f'<div class="msg-ok">{_esc(message)}</div>'
        if error:
            msgs += f'<div class="msg-err">{_esc(error)}</div>'

        title = _esc(link.get('title') or link.get('url', ''))
        url = link.get('url', '')
        domain = get_base_domain(url)
        og_img = link.get('og_image_url') or link.get('screenshot_url') or ''
        score = link.get('direct_score', 0) or 0

        # --- Determine media embed: YouTube > Bluesky > image > nothing ---
        yt_id = extract_youtube_id(url)
        bsky = is_bluesky_url(url)

        if yt_id:
            img_html = (
                f'<div class="yt-embed-wrap">'
                f'<iframe src="https://www.youtube.com/embed/{yt_id}" '
                f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
                f'allowfullscreen loading="lazy"></iframe></div>'
            )
        elif bsky:
            # Bluesky post — render placeholder, JS will fetch oEmbed
            bsky_url_esc = _esc(url)
            img_html = (
                f'<div class="bsky-embed-wrap" id="bsky-embed" data-url="{bsky_url_esc}">'
                f'<div class="lazy-loader">Loading Bluesky post&hellip;</div></div>'
            )
        elif og_img:
            img_html = f'<img src="{_esc(og_img)}" class="img-preview" alt="preview">'
        else:
            img_html = ""

        # Tags as pills with "+" button at the end
        tags_html = '<div class="tags-row">'
        for t in link.get('tags', []):
            sl = _esc(t.get('slug', ''))
            nm = _esc(t.get('name', sl))
            tags_html += f'<span class="pill">{nm}<a href="/link/{link_id}/remove-tag/{sl}" class="x">&times;</a></span>'
        tags_html += '</div>'
        if not link.get('tags'):
            tags_html = '<div class="tags-row"><span style="color:#475569;font-size:13px">No tags yet</span></div>'

        # Parent link
        parent_html = ""
        if link.get('parent'):
            p = link['parent']
            parent_html = f'<div style="margin-bottom:12px"><span style="color:#64748b;font-size:13px">Part of:</span> <a href="/link/{p["id"]}">{_esc(p.get("title") or p.get("url"))}</a></div>'

        # --- Comments section: just the input form + a placeholder for lazy-loaded notes ---
        comments_shell = f'''<div class="commenting-as" id="commenting-as"></div>
        <div class="comment-input">
            <form method="POST" action="/link/{link_id}/add-note" style="display:flex;gap:10px;width:100%">
                <textarea name="text" placeholder="Add a comment..." required rows="1"
                    onfocus="this.rows=3" onblur="if(!this.value)this.rows=1"
                    onkeydown="if(event.key===\'Enter\'&&!event.shiftKey){{event.preventDefault();this.form.submit()}}"></textarea>
                <input type="hidden" name="author" value="anon" id="comment-author">
            </form>
        </div>
        <div id="notes-container"><div class="lazy-loader">Loading comments&hellip;</div></div>'''

        # --- External discussions: shell with refresh button + placeholder ---
        ext_disc_shell = f'''<div class="card">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
                <h2 style="margin-bottom:0">External Discussions</h2>
                <form method="POST" action="/link/{link_id}/refresh-discussions" style="margin:0"><button type="submit" class="refresh-btn">&#8635; Refresh</button></form>
            </div>
            <div id="discussions-container"><div class="lazy-loader">Checking HN &amp; Reddit&hellip;</div></div>
        </div>'''

        # --- Related links: placeholder ---
        related_shell = '''<div class="card">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
                <h2 style="margin-bottom:0">Related Links</h2>
            </div>
            <div id="related-container"><div class="lazy-loader">Finding related links&hellip;</div></div>
        </div>'''

        body = f"""{msgs}
        <div class="card" style="position:relative">
            <div style="position:absolute;top:24px;right:24px">
                <form method="POST" action="/link/{link_id}/star" style="margin:0">
                    <button type="submit" class="star-btn">
                        <span class="star-icon">&#9734;</span>
                        <span class="star-count">{score}</span>
                    </button>
                </form>
            </div>
            {parent_html}
            <h1 style="margin-bottom:4px;padding-right:80px"><a href="{_esc(url)}" target="_blank" style="color:#f1f5f9;text-decoration:none">{title}</a></h1>
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
                <div style="color:#64748b;font-size:13px">
                    <a href="/browse?q={_esc(domain)}" style="color:#64748b">{_esc(domain)}</a>
                    &middot; {time_ago(link.get('created_at'))}
                    {f' &middot; by {_esc(link.get("submitted_by") or "")}' if link.get("submitted_by") and link["submitted_by"] != "web" else ''}
                </div>
                <a href="/api/random" class="btn btn-sm" style="background:#312e81;color:#a5b4fc;border:1px solid #4338ca;text-decoration:none;margin-left:auto;white-space:nowrap">&#127922; Next Random</a>
            </div>
            {img_html}
            <div style="display:flex;align-items:baseline;gap:0;flex-wrap:wrap;margin-top:8px">
                <span style="color:#64748b;font-size:13px;margin-right:8px;font-weight:500;white-space:nowrap">Tags:</span>
                {tags_html}
            </div>
        </div>

        <div class="card">
            {comments_shell}
        </div>

        {ext_disc_shell}

        {related_shell}"""

        # Build the detail page JavaScript (as a non-f-string to avoid brace escaping)
        detail_js_code = (
            "<script>\n"
            + _JS_HELPERS
            + "\nvar LID=" + str(link_id) + ";\n"
            + r"""
// --- Load notes/comments ---
fetch('/api/link/'+LID+'/notes').then(function(r){return r.json();}).then(function(data){
    var c=document.getElementById('notes-container');var notes=data.notes||[];var h='';
    if(!notes.length){h='<p style="color:#475569;font-size:13px;padding:8px 0">No comments yet. Start the discussion!</p>';}
    else{notes.forEach(function(n){
        h+='<div class="comment"><div class="vote-col">'+
        '<button class="vote-btn up" title="Upvote">&#9650;</button>'+
        '<span class="vote-score">&middot;</span>'+
        '<button class="vote-btn down" title="Downvote">&#9660;</button>'+
        '</div><div class="comment-body">'+
        '<div class="comment-meta"><strong>'+_esc(n.display_name||n.author||'anonymous')+'</strong> &middot; '+_ago(n.created_at)+'</div>'+
        '<div class="comment-text">'+_esc(n.text||'')+'</div></div></div>';
    });}
    c.innerHTML=h;
}).catch(function(){document.getElementById('notes-container').innerHTML='<p style="color:#f87171;font-size:13px">Failed to load comments.</p>';});

// --- Load related links ---
fetch('/api/link/'+LID+'/related?limit=6').then(function(r){return r.json();}).then(function(data){
    var c=document.getElementById('related-container');var rel=data.related||[];var h='';
    if(!rel.length){h='<p style="color:#475569;font-size:13px">No related links found.</p>';}
    else{rel.forEach(function(r){
        h+='<a href="/link/'+r.id+'" class="related-link"><span class="r-title">'+_esc(r.title||r.url||'')+'</span><br><span class="r-url">'+_esc(_domain(r.url||''))+'</span></a>';
    });}
    c.innerHTML=h;
}).catch(function(){document.getElementById('related-container').innerHTML='<p style="color:#f87171;font-size:13px">Failed to load related links.</p>';});

// --- Load external discussions ---
fetch('/api/link/'+LID+'/discussions').then(function(r){return r.json();}).then(function(data){
    var c=document.getElementById('discussions-container');var disc=data.discussions||[];
    if(!disc.length){c.innerHTML='<p style="color:#475569;font-size:13px;padding:4px 0">No external discussions found yet. Click refresh to check HN and Reddit.</p>';return;}

    // Filter HN and Reddit, sort by combined score (upvotes + comments)
    var hnReddit=disc.filter(function(d){return d.platform==='hackernews'||d.platform==='reddit';});
    var bsky=disc.filter(function(d){return d.platform==='bluesky';});
    
    // Sort by score (upvotes + comments combined)
    hnReddit.sort(function(a,b){
        var scoreA=(a.score||0)+(a.num_comments||0);
        var scoreB=(b.score||0)+(b.num_comments||0);
        return scoreB-scoreA;
    });

    var h='';
    var LIM=3;
    
    // Combined HN + Reddit discussions as compact links
    hnReddit.forEach(function(d,i){
        var hide=i>=LIM?' style="display:none"':'';
        var cls=i>=LIM?' ext-disc-extra':'';
        var icon=d.platform==='reddit'?'&#129302;':'&#129412;';
        var iconColor=d.platform==='reddit'?'#ff4500':'#ff6600';
        var meta=d.platform==='reddit'?'r/'+_esc(d.subreddit||'reddit'):'Hacker News';
        h+='<a href="'+_esc(d.external_url||'#')+'" target="_blank" class="ext-disc'+cls+'"'+hide+' style="text-decoration:none">'+
            '<div class="platform-icon" style="color:'+iconColor+'">'+icon+'</div>'+
            '<div class="disc-info"><div class="disc-title">'+_esc(d.title||'Discussion')+'</div>'+
            '<div class="disc-meta">'+meta+'</div></div>'+
            '<div class="disc-stats"><span>&#9650; '+(d.score||0)+'</span><span>&#128172; '+(d.num_comments||0)+'</span></div></a>';
    });
    if(hnReddit.length>LIM){
        var ex=hnReddit.length-LIM;
        h+='<button id="disc-toggle" onclick="_toggleDisc()" style="background:none;border:1px solid #334155;color:#94a3b8;padding:8px 16px;border-radius:8px;cursor:pointer;width:100%;font-size:13px;margin-top:4px">Show '+ex+' more discussion'+(ex!==1?'s':'')+'</button>';
    }

    // Bluesky discussions as compact links (separate section if any)
    if(bsky.length>0){
        h+='<div style="margin-bottom:8px;margin-top:'+(hnReddit.length>0?'16':'0')+'px"><span style="color:#0085ff;font-weight:600;font-size:14px">&#129419; Bluesky</span></div>';
    }
    bsky.forEach(function(d){
        h+='<a href="'+_esc(d.external_url||'#')+'" target="_blank" class="ext-disc" style="text-decoration:none">'+
            '<div class="platform-icon">&#129419;</div>'+
            '<div class="disc-info"><div class="disc-title">'+_esc(d.title||'Discussion')+'</div>'+
            '<div class="disc-meta">Bluesky</div></div>'+
            '<div class="disc-stats"><span>&#9650; '+(d.score||0)+'</span><span>&#128172; '+(d.num_comments||0)+'</span></div></a>';
    });

    c.innerHTML=h;
}).catch(function(){document.getElementById('discussions-container').innerHTML='<p style="color:#f87171;font-size:13px">Failed to load discussions.</p>';});

// Toggle show/hide for discussions
function _toggleDisc(){
    var extras=document.querySelectorAll('.ext-disc-extra');var btn=document.getElementById('disc-toggle');
    if(!extras.length)return;
    var showing=extras[0].style.display!=='none';
    if(showing){
        extras.forEach(function(e){e.style.display='none';});
        btn.textContent='Show '+extras.length+' more discussion'+(extras.length!==1?'s':'');
    }else{
        extras.forEach(function(e){e.style.display='';});
        btn.textContent='Show less';
    }
}
"""
            + "</script>"
        )

        return HTMLResponse(dark_page(title, body, extra_scripts=detail_js_code))

    # ========== POST /link/{id}/add-note ==========
    @app.post("/link/{link_id}/add-note")
    async def page_add_note(link_id: int, request: Request, text: str = Form(...), author: str = Form("anon")):
        author = author.strip() or "anon"
        insert_data = {'link_id': link_id, 'author': author, 'text': text.strip()}
        # Attach user_id from middleware
        user_id = getattr(getattr(request, 'state', None), 'user_id', None)
        if user_id:
            insert_data['user_id'] = user_id
            # Use display_name as author if default
            if author in ('anon', 'anonymous'):
                display_name = getattr(request.state, 'display_name', None)
                if display_name and display_name != 'Anonymous':
                    insert_data['author'] = display_name
        supabase.table('notes').insert(insert_data).execute()
        return RedirectResponse(url=f"/link/{link_id}", status_code=303)

    # ========== POST /link/{id}/add-tags ==========
    @app.post("/link/{link_id}/add-tags")
    async def page_add_tags(link_id: int, tags: str = Form(...)):
        for tag_name in tags.split(','):
            tag_name = tag_name.strip()
            if tag_name:
                tag = get_or_create_tag(supabase, tag_name)
                if tag:
                    try:
                        supabase.table('link_tags').insert({
                            'link_id': link_id, 'tag_id': tag['id'], 'added_by': 'web',
                        }).execute()
                    except Exception:
                        pass
        return RedirectResponse(url=f"/link/{link_id}", status_code=303)

    # ========== POST /link/{id}/star ==========
    @app.post("/link/{link_id}/star")
    async def page_star_link(link_id: int):
        # Increment direct_score by 1 (acts as a star/upvote)
        link_resp = supabase.table('links').select('direct_score').eq('id', link_id).execute()
        if link_resp.data:
            current = link_resp.data[0].get('direct_score', 0) or 0
            supabase.table('links').update({'direct_score': current + 1}).eq('id', link_id).execute()
        return RedirectResponse(url=f"/link/{link_id}", status_code=303)

    # ========== POST /link/{id}/refresh-discussions ==========
    @app.post("/link/{link_id}/refresh-discussions")
    async def page_refresh_discussions(link_id: int, background_tasks: BackgroundTasks):
        link_resp = supabase.table('links').select('url').eq('id', link_id).execute()
        if link_resp.data:
            url = link_resp.data[0]['url']
            background_tasks.add_task(_fetch_discussions_bg, link_id, url)
        return RedirectResponse(url=f"/link/{link_id}?message=Checking+HN+and+Reddit...", status_code=303)

    # ========== GET /link/{id}/remove-tag/{slug} ==========
    @app.get("/link/{link_id}/remove-tag/{slug}")
    async def page_remove_tag(link_id: int, slug: str):
        tag_resp = supabase.table('tags').select('id').eq('slug', slug).execute()
        if tag_resp.data:
            supabase.table('link_tags').delete().eq('link_id', link_id).eq('tag_id', tag_resp.data[0]['id']).execute()
        return RedirectResponse(url=f"/link/{link_id}", status_code=303)

    # ========== GET /browse — lazy-loaded grid ==========
    @app.get("/browse", response_class=HTMLResponse)
    async def page_browse(tag: Optional[str] = None, sort: Optional[str] = "recent", q: Optional[str] = None):
        try:
            # Still fetch tags server-side for the tag bar (it's fast)
            all_tags_resp = supabase.table('tags').select('slug, name').order('name').execute()
            all_tags = all_tags_resp.data or []

            # Sort bar
            def sl(s, label):
                act = ' active' if sort == s else ''
                params = f'sort={s}'
                if tag:
                    params += f'&tag={_esc(tag)}'
                if q:
                    params += f'&q={_esc(q)}'
                return f'<a href="/browse?{params}" class="{act}">{label}</a>'

            sort_html = f'''<div class="sort-bar">
                <span style="color:#64748b;font-size:13px">Sort:</span>
                {sl("recent","&#128337; Recent")}
                {sl("score","&#11088; Top")}
                {sl("noted","&#128221; Most Noted")}
                <a href="/api/random" style="margin-left:auto;background:#312e81;border-color:#4338ca;color:#a5b4fc">&#127922; Random Link</a>
            </div>'''

            # Tag filter bar
            tag_html = '<div class="sort-bar"><span style="color:#64748b;font-size:13px">Tags:</span>'
            act_all = ' active' if not tag else ''
            tag_html += f'<a href="/browse?sort={sort}" class="{act_all}">All</a>'
            for t in all_tags:
                ac = ' active' if tag == t['slug'] else ''
                tag_html += f'<a href="/browse?tag={_esc(t["slug"])}&sort={sort}" class="{ac}">{_esc(t["name"])}</a>'
            tag_html += '</div>'

            # Filter banner when searching by domain/query
            filter_html = ''
            if q:
                filter_html = f'''<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;padding:10px 16px;background:#1e293b;border:1px solid #334155;border-radius:8px">
                    <span style="color:#94a3b8;font-size:14px">Showing links from <strong style="color:#e2e8f0">{_esc(q)}</strong></span>
                    <a href="/browse" style="color:#64748b;font-size:18px;line-height:1;margin-left:auto;text-decoration:none" title="Clear filter">&times;</a>
                </div>'''

            # Skeleton grid placeholder (shows while JS loads real content)
            skeleton_cards = '<div class="grid" id="links-grid">'
            for _ in range(6):
                skeleton_cards += '''<div class="skeleton-card">
                    <div class="skel-thumb"></div>
                    <div class="skel-body">
                        <div class="skel-line w75"></div>
                        <div class="skel-line w50"></div>
                        <div class="skel-line w30"></div>
                    </div>
                </div>'''
            skeleton_cards += '</div>'

            body = f'''{filter_html}{sort_html}{tag_html}{skeleton_cards}'''

            # Build browse page JavaScript
            browse_js_code = (
                "<script>\n"
                + _JS_HELPERS
                + "\nvar _sort=" + _json.dumps(sort or "recent") + ";"
                + "\nvar _tag=" + _json.dumps(tag or "") + ";"
                + "\nvar _q=" + _json.dumps(q or "") + ";\n"
                + r"""
var apiUrl='/api/links?limit=60';
if(_sort)apiUrl+='&sort='+encodeURIComponent(_sort);
if(_tag)apiUrl+='&tag='+encodeURIComponent(_tag);
if(_q)apiUrl+='&q='+encodeURIComponent(_q);

fetch(apiUrl).then(function(r){return r.json();}).then(function(data){
    var c=document.getElementById('links-grid');
    var links=data.links||[];
    // Client-side sort for "noted"
    if(_sort==='noted'){links.sort(function(a,b){return(b.note_count||0)-(a.note_count||0);});}

    if(!links.length){
        c.innerHTML='<div class="empty-state"><div class="icon">&#128279;</div><p>No links found.</p><p style="margin-top:12px"><a href="/add" class="btn btn-primary">Add the first one</a></p></div>';
        return;
    }
    var h='';
    links.forEach(function(lk){
        var t=_esc(lk.title||lk.url||'');
        var d=_domain(lk.url||'');
        var og=lk.og_image_url||'';
        var nc=lk.note_count||0;
        var sc=lk.direct_score||0;
        var thumb=og
            ?'<img src="'+_esc(og)+'" class="thumb" alt="" loading="lazy">'
            :'<div class="thumb-placeholder">&#127760;</div>';
        var pills='';
        (lk.tags||[]).slice(0,4).forEach(function(tg){
            pills+='<span class="pill-sm">'+_esc(tg.name||tg.slug||'')+'</span>';
        });
        h+='<a href="/link/'+lk.id+'" class="link-card">'+thumb+
            '<div class="body"><div class="card-title">'+t+'</div>'+
            '<div class="card-domain">'+_esc(d)+'</div>'+
            '<div class="card-pills">'+pills+'</div>'+
            '<div class="card-meta"><span>&#128172; '+nc+'</span><span>&#11088; '+sc+'</span></div>'+
            '</div></a>';
    });
    c.innerHTML=h;
}).catch(function(){
    document.getElementById('links-grid').innerHTML='<div class="msg-err">Failed to load links. <a href="/browse">Retry</a></div>';
});
"""
                + "</script>"
            )

            return HTMLResponse(dark_page("Browse", body, extra_scripts=browse_js_code))
        except Exception as e:
            import traceback
            traceback.print_exc()
            return HTMLResponse(dark_page("Error", f'<div class="msg-err">Error: {_esc(str(e))}</div>'))
