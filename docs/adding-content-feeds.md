# Adding Content Feeds to Linksite

This guide explains how to add new content feeds (quotes, comics, images, memes) to Linksite.

## Overview

Content feeds are external APIs or RSS sources that provide pre-made content items like:
- **Quotes** (Quotable, ZenQuotes, Stoic quotes)
- **Webcomics** (xkcd, SMBC, PBF)
- **Memes** (Imgflip templates)
- **Images** (Unsplash, Pexels)

Unlike RSS/Reddit gatherers (which fetch links), content feeds fetch the **content itself**.

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│   External APIs     │────▶│  content_feeds.py    │
│   (xkcd, quotable)  │     │  - BaseFeed classes  │
└─────────────────────┘     │  - ContentFeedManager│
                            └──────────┬───────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │   content_feeds      │
                            │   (tracking table)   │
                            └──────────┬───────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │   content_items      │
                            │   (fetched content)  │
                            └──────────┬───────────┘
                                       │ (optional)
                                       ▼
                            ┌──────────────────────┐
                            │       links          │
                            │   (main content)     │
                            └──────────────────────┘
```

## Adding a New Feed

### Step 1: Create Feed Class

Create a new feed class in `content_feeds.py` that extends `BaseFeed`:

```python
class MyNewFeed(BaseFeed):
    """Fetch content from My New API."""
    
    name = "mynewfeed"  # Unique identifier
    feed_type = "api"    # 'api' or 'rss'
    ENDPOINT = "https://api.example.com/content"
    
    async def fetch(self, last_item_id: Optional[str] = None, 
                    etag: Optional[str] = None,
                    last_modified: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch new content from the feed.
        
        Must return:
        {
            "items": List[ContentItem],
            "last_item_id": str,  # For incremental fetching
            "etag": Optional[str],
            "last_modified": Optional[str],
            "not_modified": bool,
        }
        """
        client = await self._get_client()
        
        # Fetch from API
        response = await client.get(self.ENDPOINT)
        response.raise_for_status()
        data = response.json()
        
        items = []
        latest_id = None
        
        for item in data:
            item_id = item.get("id")
            latest_id = item_id
            
            items.append(ContentItem(
                external_id=str(item_id),
                content_type="quote",  # or 'comic', 'meme', 'image'
                title=item.get("title"),
                content=item.get("text"),
                image_url=item.get("image_url"),
                source_url=item.get("url"),
                author=item.get("author"),
                tags=item.get("tags", []),
                meta_json={
                    # Any extra metadata
                },
            ))
        
        return {
            "items": items,
            "last_item_id": latest_id,
            "etag": None,
            "last_modified": None,
            "not_modified": False,
        }
```

### Step 2: Register the Feed

Add your feed to the `FEED_REGISTRY` in `content_feeds.py`:

```python
FEED_REGISTRY: Dict[str, type] = {
    "quotable": QuotableFeed,
    "xkcd": XkcdFeed,
    "smbc": SmbcFeed,
    "mynewfeed": MyNewFeed,  # Add here
}
```

### Step 3: Add Database Entry

Add your feed to the `content_feeds` table. Either:

**Option A: Migration SQL**
```sql
INSERT INTO content_feeds (name, feed_type, endpoint_url, description, fetch_interval_hours, config)
VALUES 
    ('mynewfeed', 'api', 'https://api.example.com/content',
     'My New Feed - description here', 6.0,
     '{"batch_size": 10}'::jsonb);
```

**Option B: Via Admin API**
```bash
# Not yet implemented - use SQL for now
```

### Step 4: Test

1. Go to `/admin` and find your feed in the Content Feeds section
2. Click "Fetch" to manually trigger a fetch
3. Check `/admin/content-feeds` to see fetched items
4. Click "Ingest" on an item to convert it to a link

## ContentItem Fields

| Field | Type | Description |
|-------|------|-------------|
| `external_id` | str | **Required**. Unique ID from source |
| `content_type` | str | **Required**. One of: 'quote', 'comic', 'meme', 'image' |
| `title` | str | Optional title |
| `content` | str | Main text content (quote text, alt text, description) |
| `image_url` | str | Direct URL to image |
| `source_url` | str | Link to original page |
| `author` | str | Creator/author name |
| `tags` | List[str] | Tags/categories from source |
| `meta_json` | dict | Any extra metadata |
| `published_at` | datetime | Original publish date if known |

## Best Practices

### 1. Respect Rate Limits

- Use reasonable fetch intervals (6-12 hours minimum)
- Support `ETag` and `Last-Modified` headers when available
- Don't fetch more than needed (use `last_item_id` for incremental updates)

### 2. Handle Errors Gracefully

The manager tracks `consecutive_errors` and `last_error`. Your fetch method should:
- Raise exceptions on failure (they'll be caught and logged)
- Return `not_modified: True` when nothing new

### 3. Use Incremental Fetching

For APIs with stable IDs (like xkcd's comic number):
```python
async def fetch(self, last_item_id: Optional[str] = None, **kwargs):
    # Get latest
    latest_num = await self._get_latest_num()
    last_num = int(last_item_id) if last_item_id else 0
    
    if latest_num <= last_num:
        return {"items": [], "not_modified": True, ...}
    
    # Only fetch new items
    items = []
    for num in range(last_num + 1, latest_num + 1):
        items.append(await self._fetch_item(num))
    
    return {"items": items, "last_item_id": str(latest_num), ...}
```

### 4. RSS Feeds

For RSS feeds, use `feedparser` and track by `<guid>` or `<link>`:

```python
class MyRSSFeed(BaseFeed):
    name = "myrss"
    feed_type = "rss"
    RSS_URL = "https://example.com/feed.xml"
    
    async def fetch(self, last_item_id: Optional[str] = None, **kwargs):
        client = await self._get_client()
        response = await client.get(self.RSS_URL)
        feed = feedparser.parse(response.text)
        
        items = []
        for entry in feed.entries:
            entry_id = entry.get("id") or entry.get("link")
            
            # Stop at last seen item
            if last_item_id and entry_id == last_item_id:
                break
            
            items.append(ContentItem(
                external_id=self._hash_id(entry_id),
                content_type="comic",
                title=entry.get("title"),
                content=entry.get("summary"),
                source_url=entry.get("link"),
                ...
            ))
        
        return {"items": items, ...}
```

## Configuration Options

Feed-specific config is stored in the `config` JSONB column:

| Option | Description | Example |
|--------|-------------|---------|
| `batch_size` | Number of items to fetch per request | `10` |
| `max_items` | Maximum items to process from RSS | `20` |
| `tags` | Filter by specific tags (if API supports) | `["philosophy"]` |
| `check_latest` | Whether to check for latest before fetching | `true` |

Access in your feed class via `self.config`:
```python
batch_size = self.config.get("batch_size", 10)
```

## Monitoring

- **Admin Dashboard** (`/admin`): See feed status, errors, last fetch time
- **Content Items** (`/admin/content-feeds`): Browse fetched items, ingest to links
- **API**: `/api/admin/content-feeds` returns JSON status

## Troubleshooting

### "Unknown feed type: xyz"

Your feed isn't in `FEED_REGISTRY`. Add it there.

### "Error fetching feed"

Check:
1. API endpoint is correct
2. Response parsing matches actual API response
3. Network connectivity

### Items not appearing

1. Check if items already exist (by `external_id`)
2. Verify `ContentItem` fields are populated correctly
3. Check database for errors in `content_feeds.last_error`
