"""
Feed Ingestion System - FastAPI Application
"""

import os
from datetime import datetime
from typing import Optional, List
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Template
from supabase import create_client, Client
import feedparser

from ingest import scrape_youtube, scrape_article, vectorize, ContentExtractor

# Load environment variables
load_dotenv()

app = FastAPI(title="Link Discovery - Feed Ingestion System")

# Initialize Supabase client
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)


# HTML Templates
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
        h1 {
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }
        .stats {
            background: white;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stats p {
            margin: 5px 0;
            color: #666;
        }
        .warning {
            background: #fff3cd;
            color: #856404;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #ffc107;
        }
        .link-list {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .link-item {
            padding: 15px 20px;
            border-bottom: 1px solid #eee;
            transition: background-color 0.2s;
        }
        .link-item:hover {
            background-color: #f9f9f9;
        }
        .link-item:last-child {
            border-bottom: none;
        }
        .link-number {
            display: inline-block;
            width: 40px;
            color: #999;
            font-weight: bold;
        }
        .link-title {
            font-size: 16px;
            font-weight: 500;
            color: #1a73e8;
            margin-bottom: 5px;
        }
        .link-url {
            font-size: 13px;
            color: #5f6368;
            word-break: break-all;
        }
        .link-meta {
            font-size: 12px;
            color: #999;
            margin-top: 5px;
        }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            margin-right: 8px;
            font-weight: 500;
        }
        .badge-youtube {
            background: #ff0000;
            color: white;
        }
        .badge-website {
            background: #4CAF50;
            color: white;
        }
        .nav-links {
            margin-bottom: 20px;
        }
        .nav-links a {
            color: #1a73e8;
            text-decoration: none;
            margin-right: 20px;
        }
        .nav-links a:hover {
            text-decoration: underline;
        }
        a {
            color: inherit;
            text-decoration: none;
        }
        a:hover .link-title {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <h1>🔗 Link Discovery - Top 50 Links</h1>

    <div class="nav-links">
        <a href="/admin">⚙️ Admin Dashboard</a>
    </div>

    {% if warning %}
    <div class="warning">
        <strong>Note:</strong> {{ warning }}
    </div>
    {% endif %}

    {% if stats %}
    <div class="stats">
        <p><strong>Total Links:</strong> {{ stats.total }}</p>
        <p><strong>YouTube Videos:</strong> {{ stats.youtube }}</p>
        <p><strong>Websites:</strong> {{ stats.websites }}</p>
    </div>
    {% endif %}

    {% if links %}
    <div class="link-list">
        {% for link in links %}
        <div class="link-item">
            <span class="link-number">{{ loop.index }}.</span>
            <a href="{{ link.url }}" target="_blank">
                <div class="link-title">{{ link.title or 'Untitled' }}</div>
                <div class="link-url">{{ link.url }}</div>
                <div class="link-meta">
                    {% if link.meta_json and link.meta_json.type %}
                    <span class="badge badge-{{ link.meta_json.type }}">{{ link.meta_json.type }}</span>
                    {% endif %}
                    {% if link.meta_json and link.meta_json.channel_name %}
                    Channel: {{ link.meta_json.channel_name }}
                    {% endif %}
                    <span style="margin-left: 10px;">Added: {{ link.created_at[:10] if link.created_at else 'N/A' }}</span>
                </div>
            </a>
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
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }
        .card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .add-feed-form {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .add-feed-form input[type="text"] {
            flex: 1;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }
        .add-feed-form select {
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            background: white;
        }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            font-size: 14px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #4CAF50;
            color: white;
        }
        .btn-primary:hover {
            background: #45a049;
        }
        .btn-warning {
            background: #ff9800;
            color: white;
        }
        .btn-warning:hover {
            background: #e68900;
        }
        .btn-danger {
            background: #f44336;
            color: white;
        }
        .btn-danger:hover {
            background: #da190b;
        }
        .feed-list {
            list-style: none;
            padding: 0;
        }
        .feed-item {
            padding: 15px;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .feed-item:last-child {
            border-bottom: none;
        }
        .feed-info {
            flex: 1;
        }
        .feed-url {
            font-weight: 500;
            color: #333;
            margin-bottom: 5px;
        }
        .feed-meta {
            font-size: 12px;
            color: #999;
        }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            margin-right: 8px;
            font-weight: 500;
        }
        .badge-rss {
            background: #ff6b6b;
            color: white;
        }
        .badge-youtube {
            background: #ff0000;
            color: white;
        }
        .badge-website {
            background: #4CAF50;
            color: white;
        }
        .sync-status {
            background: #e3f2fd;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
            border-left: 4px solid #2196f3;
        }
        .success-message {
            background: #d4edda;
            color: #155724;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 20px;
            border-left: 4px solid #28a745;
        }
        .nav-links {
            margin-bottom: 20px;
        }
        .nav-links a {
            color: #1a73e8;
            text-decoration: none;
            margin-right: 20px;
        }
        .nav-links a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <h1>📡 Feed Manager - Admin Dashboard</h1>

    <div class="nav-links">
        <a href="/">← Back to Links</a>
    </div>

    {% if message %}
    <div class="success-message">{{ message }}</div>
    {% endif %}

    <div class="card">
        <h2>Add New Feed</h2>
        <form method="POST" action="/admin/add-feed" class="add-feed-form">
            <input type="text" name="url" placeholder="Feed URL (RSS, YouTube channel, or website)" required>
            <select name="type" required>
                <option value="">Select Type</option>
                <option value="rss">RSS Feed</option>
                <option value="youtube">YouTube</option>
                <option value="website">Website</option>
            </select>
            <button type="submit" class="btn btn-primary">Add Feed</button>
        </form>
    </div>

    <div class="card">
        <h2>Current Feeds ({{ feed_count }})</h2>
        <form method="POST" action="/admin/sync">
            <button type="submit" class="btn btn-warning">🔄 Sync All Feeds Now</button>
        </form>

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
                        {% if feed.last_scraped_at %}
                        | Last scraped: {{ feed.last_scraped_at[:16] }}
                        {% endif %}
                    </div>
                </div>
                <div style="display: flex; gap: 10px;">
                    <form method="POST" action="/admin/sync-feed/{{ feed.id }}" style="display: inline;">
                        <button type="submit" class="btn btn-primary">Sync</button>
                    </form>
                    <form method="POST" action="/admin/delete-feed/{{ feed.id }}" style="display: inline;">
                        <button type="submit" class="btn btn-danger" onclick="return confirm('Delete this feed?')">Delete</button>
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


@app.get("/")
async def root():
    """Redirect to links view."""
    return RedirectResponse(url="/links")


@app.get("/links", response_class=HTMLResponse)
async def view_links():
    """View all links from the database."""
    try:
        # Fetch links from database
        response = supabase.table('links').select('*').order('created_at', desc=True).limit(50).execute()
        links = response.data if response.data else []

        # Get stats
        stats = None
        if links:
            stats = {
                'total': len(links),
                'youtube': sum(1 for link in links if link.get('meta_json', {}).get('type') == 'youtube'),
                'websites': sum(1 for link in links if link.get('meta_json', {}).get('type') == 'website')
            }

        warning = None
        if not links:
            warning = "No links found in the database."

        # Render template with Jinja2
        template = Template(LINKS_TEMPLATE)
        return HTMLResponse(template.render(links=links, stats=stats, warning=warning))

    except Exception as e:
        return HTMLResponse(f"<h1>Error loading links</h1><p>{str(e)}</p>")


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(message: Optional[str] = None):
    """Admin dashboard for managing feeds."""
    try:
        # Fetch all feeds
        response = supabase.table('feeds').select('*').order('created_at', desc=True).execute()
        feeds = response.data if response.data else []

        # Render template with Jinja2
        template = Template(ADMIN_TEMPLATE)
        return HTMLResponse(template.render(
            message=message,
            feed_count=len(feeds),
            feeds=feeds
        ))

    except Exception as e:
        return HTMLResponse(f"<h1>Error loading admin</h1><p>{str(e)}</p>")


@app.post("/admin/add-feed")
async def add_feed(url: str = Form(...), type: str = Form(...)):
    """Add a new feed to monitor."""
    try:
        # Insert into feeds table
        supabase.table('feeds').insert({
            'url': url,
            'type': type,
            'last_scraped_at': None
        }).execute()

        return RedirectResponse(url="/admin?message=Feed added successfully!", status_code=303)

    except Exception as e:
        return RedirectResponse(url=f"/admin?message=Error: {str(e)}", status_code=303)


@app.post("/admin/delete-feed/{feed_id}")
async def delete_feed(feed_id: int):
    """Delete a feed."""
    try:
        supabase.table('feeds').delete().eq('id', feed_id).execute()
        return RedirectResponse(url="/admin?message=Feed deleted successfully!", status_code=303)

    except Exception as e:
        return RedirectResponse(url=f"/admin?message=Error: {str(e)}", status_code=303)


@app.post("/admin/sync")
async def sync_feeds(background_tasks: BackgroundTasks):
    """Trigger background sync of all feeds."""
    background_tasks.add_task(sync_all_feeds)
    return RedirectResponse(url="/admin?message=Sync started! Check back in a few minutes.", status_code=303)


@app.post("/admin/sync-feed/{feed_id}")
async def sync_single_feed(feed_id: int, background_tasks: BackgroundTasks):
    """Trigger background sync of a single feed."""
    background_tasks.add_task(sync_feed_by_id, feed_id)
    return RedirectResponse(url="/admin?message=Syncing feed...", status_code=303)


async def sync_feed_by_id(feed_id: int):
    """Sync a single feed by ID."""
    try:
        # Get the feed
        response = supabase.table('feeds').select('*').eq('id', feed_id).execute()
        feeds = response.data if response.data else []

        if not feeds:
            print(f"Feed {feed_id} not found")
            return

        feed = feeds[0]
        await process_single_feed(feed)

    except Exception as e:
        print(f"Error syncing feed {feed_id}: {str(e)}")


async def sync_all_feeds():
    """
    Background task to sync all feeds.
    Loops through feeds, fetches new content, and stores in database.
    """
    print("Starting feed sync...")

    try:
        # Get all feeds
        response = supabase.table('feeds').select('*').execute()
        feeds = response.data if response.data else []

        print(f"Found {len(feeds)} feeds to sync")

        for feed in feeds:
            await process_single_feed(feed)

        print("\nFeed sync completed!")

    except Exception as e:
        print(f"Error in sync_all_feeds: {str(e)}")


async def process_single_feed(feed: dict):
    """Process a single feed."""
    feed_id = feed['id']
    feed_url = feed['url']
    feed_type = feed['type']

    print(f"\nSyncing {feed_type} feed: {feed_url}")

    try:
        if feed_type == 'rss':
            # Parse RSS feed
            parsed = feedparser.parse(feed_url)

            for entry in parsed.entries[:10]:  # Process up to 10 latest entries
                link = entry.get('link', '')
                if not link:
                    continue

                # Check if link already exists
                existing = supabase.table('links').select('id').eq('url', link).execute()
                if existing.data:
                    print(f"  Skipping existing link: {link}")
                    continue

                # Scrape and ingest the new link
                print(f"  Processing new link: {link}")
                await ingest_link(link, entry.get('title', ''), entry.get('summary', ''))

        elif feed_type == 'youtube':
            # For YouTube, just scrape the URL directly
            existing = supabase.table('links').select('id').eq('url', feed_url).execute()
            if not existing.data:
                print(f"  Processing YouTube: {feed_url}")
                await ingest_link(feed_url, '', '')

        elif feed_type == 'website':
            # For website, just scrape the URL directly
            existing = supabase.table('links').select('id').eq('url', feed_url).execute()
            if not existing.data:
                print(f"  Processing website: {feed_url}")
                await ingest_link(feed_url, '', '')

        # Update last_scraped_at
        supabase.table('feeds').update({
            'last_scraped_at': datetime.utcnow().isoformat()
        }).eq('id', feed_id).execute()

        print(f"  ✓ Feed synced successfully")

    except Exception as e:
        print(f"  ✗ Error syncing feed: {str(e)}")


async def ingest_link(url: str, title: str = '', description: str = ''):
    """
    Ingest a single link: scrape content, generate embeddings, store in DB.
    """
    try:
        extractor = ContentExtractor()

        # Determine if YouTube or regular website
        if extractor.is_youtube_url(url):
            data = scrape_youtube(url)
        else:
            data = scrape_article(url)

        # Use provided title/description if available, otherwise use scraped
        final_title = title or data.get('title', '')
        final_content = description or data.get('description', '')

        # Generate vector embedding
        vector = vectorize(final_content[:5000] if final_content else '')

        # Prepare metadata
        meta_json = {
            'type': data.get('type', 'website'),
        }

        if data.get('type') == 'youtube':
            meta_json['channel_name'] = data.get('channel', '')
            meta_json['thumbnail'] = data.get('thumbnail', '')
        else:
            meta_json['og_image'] = data.get('og_image', '')

        # Insert into database
        supabase.table('links').insert({
            'url': url,
            'title': final_title,
            'content': final_content,
            'meta_json': meta_json,
            'content_vector': vector
        }).execute()

        print(f"    ✓ Ingested: {final_title}")

    except Exception as e:
        print(f"    ✗ Error ingesting {url}: {str(e)}")
        raise


if __name__ == "__main__":
    import uvicorn
    # Use PORT environment variable (set by Fly.io) or default to 8080
    port = int(os.getenv('PORT', 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
