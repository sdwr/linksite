"""
Feed Ingestion System - FastAPI Application
"""

import os
import asyncio
import threading
from datetime import datetime
from typing import Optional, List
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template
from supabase import create_client, Client
import feedparser

from ingest import (
    scrape_youtube, scrape_article, vectorize, ContentExtractor,
    parse_youtube_channel, parse_rss_feed, parse_reddit_feed,
    parse_bluesky_feed
)

load_dotenv()

app = FastAPI(title="Link Discovery - Feed Ingestion System")

supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

# Track active sync tasks for cancellation
_active_syncs: dict = {}  # feed_id -> {"cancel": False}
_sync_all_cancel = threading.Event()


# â”€â”€â”€ HTML Templates â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

LINKS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Link Discovery - Top 50 Links</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
        .stats {
            background: white; padding: 15px; border-radius: 8px;
            margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stats p { margin: 5px 0; color: #666; }
        .warning {
            background: #fff3cd; color: #856404; padding: 15px; border-radius: 8px;
            margin-bottom: 20px; border-left: 4px solid #ffc107;
        }
        .link-list {
            background: white; border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden;
        }
        .link-item {
            padding: 15px 20px; border-bottom: 1px solid #eee;
            transition: background-color 0.2s;
            display: flex; justify-content: space-between; align-items: flex-start;
        }
        .link-item:hover { background-color: #f9f9f9; }
        .link-item:last-child { border-bottom: none; }
        .link-content { flex: 1; }
        .link-number { display: inline-block; width: 40px; color: #999; font-weight: bold; }
        .link-title { font-size: 16px; font-weight: 500; color: #1a73e8; margin-bottom: 5px; }
        .link-url { font-size: 13px; color: #5f6368; word-break: break-all; }
        .link-meta { font-size: 12px; color: #999; margin-top: 5px; }
        .badge {
            display: inline-block; padding: 3px 8px; border-radius: 12px;
            font-size: 11px; margin-right: 8px; font-weight: 500;
        }
        .badge-youtube { background: #ff0000; color: white; }
        .badge-website { background: #4CAF50; color: white; }
        .badge-rss { background: #ff6b6b; color: white; }
        .badge-reddit { background: #ff4500; color: white; }
        .badge-bluesky { background: #0085ff; color: white; }
        .nav-links { margin-bottom: 20px; }
        .nav-links a { color: #1a73e8; text-decoration: none; margin-right: 20px; }
        .nav-links a:hover { text-decoration: underline; }
        a { color: inherit; text-decoration: none; }
        a:hover .link-title { text-decoration: underline; }
        .btn {
            padding: 6px 12px; border: none; border-radius: 4px;
            font-size: 12px; cursor: pointer; font-weight: 500; transition: all 0.2s;
        }
        .btn-danger { background: #f44336; color: white; }
        .btn-danger:hover { background: #da190b; }
        .success-message {
            background: #d4edda; color: #155724; padding: 12px; border-radius: 4px;
            margin-bottom: 20px; border-left: 4px solid #28a745;
        }
    </style>
</head>
<body>
    <h1>ðŸ”— Link Discovery - Top 50 Links</h1>
    <div class="nav-links">
        <a href="/admin">âš™ï¸ Admin Dashboard</a>
    </div>
    {% if message %}
    <div class="success-message">{{ message }}</div>
    {% endif %}
    {% if warning %}
    <div class="warning"><strong>Note:</strong> {{ warning }}</div>
    {% endif %}
    {% if stats %}
    <div class="stats">
        <p><strong>Total Links:</strong> {{ stats.total }}</p>
    </div>
    {% endif %}
    {% if links %}
    <div class="link-list">
        {% for link in links %}
        <div class="link-item">
            <div class="link-content">
                <span class="link-number">{{ loop.index }}.</span>
                <a href="{{ link.url }}" target="_blank">
                    <div class="link-title">{{ link.title or 'Untitled' }}</div>
                    <div class="link-url">{{ link.url }}</div>
                    <div class="link-meta">
                        {% if link.meta_json and link.meta_json.type %}
                        <span class="badge badge-{{ link.meta_json.type }}">{{ link.meta_json.type }}</span>
                        {% endif %}
                        {% if link.meta_json and link.meta_json.channel_name %}
                        {{ link.meta_json.channel_name }} Â·
                        {% endif %}
                        {% if link.meta_json and link.meta_json.author_handle %}
                        @{{ link.meta_json.author_handle }} Â·
                        {% endif %}
                        Added: {{ link.created_at[:10] if link.created_at else 'N/A' }}
                    </div>
                </a>
            </div>
            <form method="POST" action="/links/delete/{{ link.id }}" style="margin-left: 10px;">
                <button type="submit" class="btn btn-danger" onclick="return confirm('Delete this link?')">âœ•</button>
            </form>
        </div>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Feed Manager - Admin Dashboard</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;
        }
        h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
        .card {
            background: white; padding: 20px; border-radius: 8px;
            margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .add-feed-form { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        .add-feed-form input[type="text"] {
            flex: 1; min-width: 300px; padding: 10px; border: 1px solid #ddd;
            border-radius: 4px; font-size: 14px;
        }
        .add-feed-form select {
            padding: 10px; border: 1px solid #ddd; border-radius: 4px;
            font-size: 14px; background: white;
        }
        .btn {
            padding: 10px 20px; border: none; border-radius: 4px;
            font-size: 14px; cursor: pointer; font-weight: 500; transition: all 0.2s;
        }
        .btn-primary { background: #4CAF50; color: white; }
        .btn-primary:hover { background: #45a049; }
        .btn-warning { background: #ff9800; color: white; }
        .btn-warning:hover { background: #e68900; }
        .btn-danger { background: #f44336; color: white; }
        .btn-danger:hover { background: #da190b; }
        .btn-cancel { background: #9e9e9e; color: white; }
        .btn-cancel:hover { background: #757575; }
        .feed-list { list-style: none; padding: 0; }
        .feed-item {
            padding: 15px; border-bottom: 1px solid #eee;
            display: flex; justify-content: space-between; align-items: center;
        }
        .feed-item:last-child { border-bottom: none; }
        .feed-info { flex: 1; }
        .feed-url { font-weight: 500; color: #333; margin-bottom: 5px; }
        .feed-meta { font-size: 12px; color: #999; }
        .badge {
            display: inline-block; padding: 3px 8px; border-radius: 12px;
            font-size: 11px; margin-right: 8px; font-weight: 500;
        }
        .badge-rss { background: #ff6b6b; color: white; }
        .badge-youtube { background: #ff0000; color: white; }
        .badge-website { background: #4CAF50; color: white; }
        .badge-reddit { background: #ff4500; color: white; }
        .badge-bluesky { background: #0085ff; color: white; }
        .status-syncing { color: #2196f3; font-weight: 500; }
        .status-error { color: #f44336; font-weight: 500; }
        .status-idle { color: #4CAF50; }
        .success-message {
            background: #d4edda; color: #155724; padding: 12px; border-radius: 4px;
            margin-bottom: 20px; border-left: 4px solid #28a745;
        }
        .error-message {
            background: #f8d7da; color: #721c24; padding: 12px; border-radius: 4px;
            margin-bottom: 20px; border-left: 4px solid #f44336;
        }
        .nav-links { margin-bottom: 20px; }
        .nav-links a { color: #1a73e8; text-decoration: none; margin-right: 20px; }
        .nav-links a:hover { text-decoration: underline; }
        .sync-actions { display: flex; gap: 10px; margin-bottom: 15px; }
        .type-hint {
            font-size: 12px; color: #999; margin-top: 8px; width: 100%;
        }
    </style>
</head>
<body>
    <h1>ðŸ“¡ Feed Manager - Admin Dashboard</h1>
    <div class="nav-links">
        <a href="/">â† Back to Links</a>
    </div>
    {% if message %}
    <div class="success-message">{{ message }}</div>
    {% endif %}
    {% if error %}
    <div class="error-message">{{ error }}</div>
    {% endif %}
    <div class="card">
        <h2>Add New Feed</h2>
        <form method="POST" action="/admin/add-feed" class="add-feed-form">
            <input type="text" name="url" placeholder="URL â€” YouTube channel, RSS feed, subreddit, Bluesky handle, or website" required>
            <select name="type" required>
                <option value="">Select Type</option>
                <option value="youtube">YouTube Channel</option>
                <option value="rss">RSS / Atom Feed</option>
                <option value="reddit">Reddit Subreddit</option>
                <option value="bluesky">Bluesky Account</option>
                <option value="website">Website (single page)</option>
            </select>
            <button type="submit" class="btn btn-primary">Add Feed</button>
        </form>
        <div class="type-hint">
            <strong>Examples:</strong>
            YouTube: youtube.com/@channel Â· 
            RSS: example.com/feed.xml Â·
            Reddit: reddit.com/r/programming or just "programming" Â·
            Bluesky: handle.bsky.social or bsky.app/profile/handle Â·
            Website: any URL
        </div>
    </div>
    <div class="card">
        <h2>Current Feeds ({{ feed_count }})</h2>
        <div class="sync-actions">
            <form method="POST" action="/admin/sync">
                <button type="submit" class="btn btn-warning">ðŸ”„ Sync All Feeds</button>
            </form>
            <form method="POST" action="/admin/cancel-all">
                <button type="submit" class="btn btn-cancel">â¹ Cancel All</button>
            </form>
        </div>
        {% if feeds %}
        <ul class="feed-list">
            {% for feed in feeds %}
            <li class="feed-item">
                <div class="feed-info">
                    <div class="feed-url">
                        <span class="badge badge-{{ feed.type }}">{{ feed.type.upper() }}</span>
                        {{ feed.url }}
                    </div>
                    <div class="feed-meta">
                        Added: {{ feed.created_at[:10] if feed.created_at else 'N/A' }}
                        {% if feed.link_count %}
                        Â· {{ feed.link_count }} links
                        {% endif %}
                        {% if feed.status == 'syncing' %}
                        Â· <span class="status-syncing">âŸ³ Syncing...</span>
                        {% elif feed.status == 'error' %}
                        Â· <span class="status-error">âœ— Error: {{ feed.last_error or 'Unknown' }}</span>
                        {% elif feed.last_scraped_at %}
                        Â· <span class="status-idle">Last synced: {{ feed.last_scraped_at[:16] }}</span>
                        {% else %}
                        Â· <span style="color: #999;">Never synced</span>
                        {% endif %}
                    </div>
                </div>
                <div style="display: flex; gap: 10px;">
                    {% if feed.status == 'syncing' %}
                    <form method="POST" action="/admin/cancel-feed/{{ feed.id }}" style="display: inline;">
                        <button type="submit" class="btn btn-cancel">Cancel</button>
                    </form>
                    {% else %}
                    <form method="POST" action="/admin/sync-feed/{{ feed.id }}" style="display: inline;">
                        <button type="submit" class="btn btn-primary">Sync</button>
                    </form>
                    {% endif %}
                    <form method="POST" action="/admin/delete-feed/{{ feed.id }}" style="display: inline;">
                        <button type="submit" class="btn btn-danger" onclick="return confirm('Delete this feed and all its links?')">Delete</button>
                    </form>
                </div>
            </li>
            {% endfor %}
        </ul>
        {% else %}
        <p style="color: #999; text-align: center; padding: 40px;">No feeds added yet. Add your first feed above!</p>
        {% endif %}
    </div>
</body>
</html>
"""


# â”€â”€â”€ Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/")
async def root():
    return RedirectResponse(url="/links")


@app.get("/links", response_class=HTMLResponse)
async def view_links(message: Optional[str] = None):
    try:
        response = supabase.table('links').select('*').order('created_at', desc=True).limit(50).execute()
        links = response.data or []
        stats = {'total': len(links)} if links else None
        warning = "No links found in the database." if not links else None
        template = Template(LINKS_TEMPLATE)
        return HTMLResponse(template.render(links=links, stats=stats, warning=warning, message=message))
    except Exception as e:
        return HTMLResponse(f"<h1>Error loading links</h1><p>{str(e)}</p>")


@app.post("/links/delete/{link_id}")
async def delete_link(link_id: int):
    """Delete a single link."""
    try:
        supabase.table('links').delete().eq('id', link_id).execute()
        return RedirectResponse(url="/links?message=Link deleted.", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/links?message=Error: {str(e)}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(message: Optional[str] = None, error: Optional[str] = None):
    try:
        response = supabase.table('feeds').select('*').order('created_at', desc=True).execute()
        feeds = response.data or []
        template = Template(ADMIN_TEMPLATE)
        return HTMLResponse(template.render(
            message=message, error=error,
            feed_count=len(feeds), feeds=feeds
        ))
    except Exception as e:
        return HTMLResponse(f"<h1>Error loading admin</h1><p>{str(e)}</p>")


@app.post("/admin/add-feed")
async def add_feed(url: str = Form(...), type: str = Form(...)):
    try:
        # Check for duplicate feed URL
        existing = supabase.table('feeds').select('id').eq('url', url).execute()
        if existing.data:
            return RedirectResponse(url="/admin?error=Feed already exists!", status_code=303)

        supabase.table('feeds').insert({
            'url': url,
            'type': type,
            'status': 'idle',
            'last_scraped_at': None,
            'link_count': 0,
        }).execute()
        return RedirectResponse(url="/admin?message=Feed added successfully!", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/admin?error=Error: {str(e)}", status_code=303)


@app.post("/admin/delete-feed/{feed_id}")
async def delete_feed(feed_id: int):
    try:
        # Delete associated links first
        supabase.table('links').delete().eq('feed_id', feed_id).execute()
        supabase.table('feeds').delete().eq('id', feed_id).execute()
        return RedirectResponse(url="/admin?message=Feed and its links deleted.", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/admin?error=Error: {str(e)}", status_code=303)


@app.post("/admin/sync")
async def sync_feeds(background_tasks: BackgroundTasks):
    _sync_all_cancel.clear()
    background_tasks.add_task(sync_all_feeds)
    return RedirectResponse(url="/admin?message=Sync started for all feeds!", status_code=303)


@app.post("/admin/sync-feed/{feed_id}")
async def sync_single_feed(feed_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(sync_feed_by_id, feed_id)
    return RedirectResponse(url="/admin?message=Syncing feed...", status_code=303)


@app.post("/admin/cancel-feed/{feed_id}")
async def cancel_feed_sync(feed_id: int):
    if feed_id in _active_syncs:
        _active_syncs[feed_id]["cancel"] = True
    # Also reset status
    supabase.table('feeds').update({'status': 'idle'}).eq('id', feed_id).execute()
    return RedirectResponse(url="/admin?message=Cancellation requested.", status_code=303)


@app.post("/admin/cancel-all")
async def cancel_all_syncs():
    _sync_all_cancel.set()
    for sync_state in _active_syncs.values():
        sync_state["cancel"] = True
    # Reset all syncing feeds to idle
    try:
        feeds = supabase.table('feeds').select('id').eq('status', 'syncing').execute()
        for feed in (feeds.data or []):
            supabase.table('feeds').update({'status': 'idle'}).eq('id', feed['id']).execute()
    except Exception:
        pass
    return RedirectResponse(url="/admin?message=All syncs cancelled.", status_code=303)


# â”€â”€â”€ Sync Engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def sync_feed_by_id(feed_id: int):
    try:
        response = supabase.table('feeds').select('*').eq('id', feed_id).execute()
        feeds = response.data or []
        if not feeds:
            print(f"Feed {feed_id} not found")
            return
        await process_single_feed(feeds[0])
    except Exception as e:
        print(f"Error syncing feed {feed_id}: {str(e)}")
        try:
            supabase.table('feeds').update({
                'status': 'error',
                'last_error': str(e)[:500]
            }).eq('id', feed_id).execute()
        except Exception:
            pass


async def sync_all_feeds():
    print("Starting feed sync...")
    try:
        response = supabase.table('feeds').select('*').execute()
        feeds = response.data or []
        print(f"Found {len(feeds)} feeds to sync")
        for feed in feeds:
            if _sync_all_cancel.is_set():
                print("Sync all cancelled.")
                break
            await process_single_feed(feed)
        print("\nFeed sync completed!")
    except Exception as e:
        print(f"Error in sync_all_feeds: {str(e)}")


async def process_single_feed(feed: dict):
    feed_id = feed['id']
    feed_url = feed['url']
    feed_type = feed['type']

    # Set up cancellation tracking
    _active_syncs[feed_id] = {"cancel": False}

    print(f"\nSyncing {feed_type} feed: {feed_url}")

    # Mark as syncing
    supabase.table('feeds').update({
        'status': 'syncing',
        'last_error': None
    }).eq('id', feed_id).execute()

    try:
        # Parse feed based on type
        if feed_type == 'youtube':
            items = parse_youtube_channel(feed_url)
        elif feed_type == 'rss':
            items = parse_rss_feed(feed_url)
        elif feed_type == 'reddit':
            items = parse_reddit_feed(feed_url)
        elif feed_type == 'bluesky':
            items = parse_bluesky_feed(feed_url)
        elif feed_type == 'website':
            # Website is a single-page scrape, wrap it as a list
            items = [_scrape_website_item(feed_url)]
        else:
            raise Exception(f"Unknown feed type: {feed_type}")

        print(f"  Found {len(items)} items")

        ingested = 0
        skipped = 0
        errors = 0

        for item in items:
            # Check cancellation
            if _active_syncs.get(feed_id, {}).get("cancel"):
                print(f"  Sync cancelled for feed {feed_id}")
                break

            url = item['url']
            if not url:
                continue

            # Dedup: check if URL already exists
            existing = supabase.table('links').select('id').eq('url', url).execute()
            if existing.data:
                skipped += 1
                continue

            try:
                await ingest_item(item, feed_id)
                ingested += 1
            except Exception as e:
                errors += 1
                print(f"    âœ— Error ingesting {url}: {str(e)}")

        # Update feed status
        link_count_resp = supabase.table('links').select('id', count='exact').eq('feed_id', feed_id).execute()
        link_count = link_count_resp.count if hasattr(link_count_resp, 'count') and link_count_resp.count else 0

        supabase.table('feeds').update({
            'status': 'idle',
            'last_scraped_at': datetime.utcnow().isoformat(),
            'last_error': None,
            'link_count': link_count,
        }).eq('id', feed_id).execute()

        print(f"  âœ“ Done: {ingested} new, {skipped} skipped, {errors} errors")

    except Exception as e:
        print(f"  âœ— Error syncing feed: {str(e)}")
        supabase.table('feeds').update({
            'status': 'error',
            'last_error': str(e)[:500]
        }).eq('id', feed_id).execute()

    finally:
        _active_syncs.pop(feed_id, None)


def _scrape_website_item(url: str) -> dict:
    """Scrape a single website URL and return as an item dict."""
    data = scrape_article(url)
    return {
        'url': url,
        'title': data.get('title', ''),
        'content': data.get('description', ''),
        'meta': {
            'type': 'website',
            'og_image': data.get('og_image', ''),
        }
    }


async def ingest_item(item: dict, feed_id: int):
    """Ingest a single parsed item into the database."""
    url = item['url']
    title = item.get('title', '')
    content = item.get('content', '')
    meta = item.get('meta', {})

    # Generate vector embedding
    text_for_embedding = f"{title}. {content}" if content else title
    vector = vectorize(text_for_embedding[:5000])

    supabase.table('links').insert({
        'url': url,
        'title': title,
        'content': content[:10000] if content else '',
        'meta_json': meta,
        'content_vector': vector,
        'feed_id': feed_id,
    }).execute()

    print(f"    âœ“ Ingested: {title[:80]}")


# â”€â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('PORT', 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
