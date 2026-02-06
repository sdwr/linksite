"""
Content Feeds Module — Fetch content from external APIs and RSS feeds

Supports:
- Quotable API (quotes)
- xkcd JSON API (webcomics)
- SMBC RSS (webcomics)
- Extensible for future feeds

Usage:
    from content_feeds import ContentFeedManager
    manager = ContentFeedManager(supabase_client)
    await manager.fetch_all()
"""

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass

import httpx
import feedparser


@dataclass
class ContentItem:
    """Represents a content item from any feed."""
    external_id: str
    content_type: str  # 'quote', 'comic', 'meme', 'image'
    title: Optional[str] = None
    content: Optional[str] = None
    image_url: Optional[str] = None
    source_url: Optional[str] = None
    author: Optional[str] = None
    tags: Optional[List[str]] = None
    meta_json: Optional[Dict[str, Any]] = None
    published_at: Optional[datetime] = None


class BaseFeed(ABC):
    """Abstract base class for content feeds."""
    
    name: str = "base"
    feed_type: str = "api"
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "linksite-content-feeds/0.1"},
                follow_redirects=True,
            )
        return self._http_client
    
    async def close(self):
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    @abstractmethod
    async def fetch(self, last_item_id: Optional[str] = None, 
                    etag: Optional[str] = None,
                    last_modified: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch new content from the feed.
        
        Returns:
            {
                "items": List[ContentItem],
                "last_item_id": str,  # For incremental fetching
                "etag": Optional[str],
                "last_modified": Optional[str],
                "not_modified": bool,  # True if 304 response
            }
        """
        pass


class QuotableFeed(BaseFeed):
    """Fetch quotes from the Quotable API."""
    
    name = "quotable"
    feed_type = "api"
    ENDPOINT = "https://api.quotable.io/quotes/random"
    
    async def fetch(self, last_item_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        client = await self._get_client()
        batch_size = self.config.get("batch_size", 10)
        
        try:
            # Fetch a batch of random quotes
            response = await client.get(
                self.ENDPOINT,
                params={"limit": batch_size}
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            raise RuntimeError(f"Quotable API error: {e}")
        
        items = []
        latest_id = None
        
        for quote in data:
            quote_id = quote.get("_id", "")
            if not quote_id:
                continue
            
            latest_id = quote_id  # Track the most recent
            
            items.append(ContentItem(
                external_id=quote_id,
                content_type="quote",
                title=None,  # Quotes don't have titles
                content=quote.get("content", ""),
                source_url=f"https://api.quotable.io/quotes/{quote_id}",
                author=quote.get("author", "Unknown"),
                tags=quote.get("tags", []),
                meta_json={
                    "author_slug": quote.get("authorSlug"),
                    "length": quote.get("length"),
                },
            ))
        
        return {
            "items": items,
            "last_item_id": latest_id,
            "etag": None,
            "last_modified": None,
            "not_modified": False,
        }


class XkcdFeed(BaseFeed):
    """Fetch comics from the xkcd JSON API."""
    
    name = "xkcd"
    feed_type = "api"
    LATEST_ENDPOINT = "https://xkcd.com/info.0.json"
    COMIC_ENDPOINT = "https://xkcd.com/{num}/info.0.json"
    
    async def fetch(self, last_item_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        client = await self._get_client()
        
        try:
            # Get latest comic number
            response = await client.get(self.LATEST_ENDPOINT)
            response.raise_for_status()
            latest = response.json()
            latest_num = latest.get("num", 0)
        except Exception as e:
            raise RuntimeError(f"xkcd API error: {e}")
        
        # Determine starting point
        last_num = int(last_item_id) if last_item_id else 0
        
        if latest_num <= last_num:
            # No new comics
            return {
                "items": [],
                "last_item_id": str(latest_num),
                "etag": None,
                "last_modified": None,
                "not_modified": True,
            }
        
        # Fetch new comics (limit to 5 at a time to be nice)
        max_to_fetch = min(5, latest_num - last_num)
        items = []
        
        for num in range(latest_num - max_to_fetch + 1, latest_num + 1):
            if num <= last_num:
                continue
            
            try:
                if num == latest_num:
                    comic = latest  # We already have the latest
                else:
                    resp = await client.get(self.COMIC_ENDPOINT.format(num=num))
                    resp.raise_for_status()
                    comic = resp.json()
                
                # Build source URL
                source_url = f"https://xkcd.com/{num}/"
                
                items.append(ContentItem(
                    external_id=str(comic.get("num")),
                    content_type="comic",
                    title=comic.get("title", ""),
                    content=comic.get("alt", ""),  # Alt text is the "content"
                    image_url=comic.get("img"),
                    source_url=source_url,
                    author="Randall Munroe",
                    tags=["webcomic", "xkcd"],
                    meta_json={
                        "year": comic.get("year"),
                        "month": comic.get("month"),
                        "day": comic.get("day"),
                        "transcript": comic.get("transcript"),
                        "link": comic.get("link"),
                        "news": comic.get("news"),
                    },
                    published_at=self._parse_xkcd_date(comic),
                ))
            except Exception as e:
                print(f"[xkcd] Error fetching comic #{num}: {e}")
                continue
        
        return {
            "items": items,
            "last_item_id": str(latest_num),
            "etag": None,
            "last_modified": None,
            "not_modified": False,
        }
    
    def _parse_xkcd_date(self, comic: dict) -> Optional[datetime]:
        try:
            year = int(comic.get("year", 0))
            month = int(comic.get("month", 1))
            day = int(comic.get("day", 1))
            return datetime(year, month, day, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None


class SmbcFeed(BaseFeed):
    """Fetch comics from SMBC RSS feed."""
    
    name = "smbc"
    feed_type = "rss"
    RSS_URL = "https://www.smbc-comics.com/comic/rss"
    
    async def fetch(self, last_item_id: Optional[str] = None,
                    etag: Optional[str] = None,
                    last_modified: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        client = await self._get_client()
        
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        
        try:
            response = await client.get(self.RSS_URL, headers=headers)
            
            # Handle 304 Not Modified
            if response.status_code == 304:
                return {
                    "items": [],
                    "last_item_id": last_item_id,
                    "etag": etag,
                    "last_modified": last_modified,
                    "not_modified": True,
                }
            
            response.raise_for_status()
            feed_content = response.text
            new_etag = response.headers.get("ETag")
            new_last_modified = response.headers.get("Last-Modified")
            
        except Exception as e:
            raise RuntimeError(f"SMBC RSS error: {e}")
        
        # Parse RSS
        feed = feedparser.parse(feed_content)
        items = []
        latest_id = last_item_id
        max_items = self.config.get("max_items", 10)
        
        for entry in feed.entries[:max_items]:
            # Use guid or link as unique ID
            entry_id = entry.get("id") or entry.get("link") or ""
            if not entry_id:
                continue
            
            # Skip if we've seen this before
            if last_item_id and entry_id == last_item_id:
                break
            
            if latest_id is None:
                latest_id = entry_id
            
            # Extract image from content
            image_url = self._extract_image_from_content(entry)
            
            # Parse publish date
            published_at = None
            if entry.get("published_parsed"):
                try:
                    published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pass
            
            items.append(ContentItem(
                external_id=self._hash_id(entry_id),
                content_type="comic",
                title=entry.get("title", ""),
                content=entry.get("summary", ""),
                image_url=image_url,
                source_url=entry.get("link"),
                author="Zach Weinersmith",
                tags=["webcomic", "smbc", "science"],
                meta_json={
                    "guid": entry.get("id"),
                },
                published_at=published_at,
            ))
        
        return {
            "items": items,
            "last_item_id": latest_id or last_item_id,
            "etag": new_etag,
            "last_modified": new_last_modified,
            "not_modified": False,
        }
    
    def _extract_image_from_content(self, entry: dict) -> Optional[str]:
        """Extract comic image URL from RSS content."""
        from bs4 import BeautifulSoup
        
        content = entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""
        if not content:
            content = entry.get("summary", "")
        
        if not content:
            return None
        
        soup = BeautifulSoup(content, "html.parser")
        img = soup.find("img")
        return img.get("src") if img else None
    
    def _hash_id(self, text: str) -> str:
        """Create a short hash ID from text."""
        return hashlib.md5(text.encode()).hexdigest()[:16]


# Registry of available feeds
FEED_REGISTRY: Dict[str, type] = {
    "quotable": QuotableFeed,
    "xkcd": XkcdFeed,
    "smbc": SmbcFeed,
}


class ContentFeedManager:
    """
    Manages all content feeds: fetching, storing, and ingesting.
    """
    
    def __init__(self, db, broadcast_fn: Callable = None):
        self.db = db
        self._broadcast = broadcast_fn or (lambda e: None)
        self._feeds: Dict[str, BaseFeed] = {}
    
    def _get_feed_instance(self, name: str, config: dict = None) -> Optional[BaseFeed]:
        """Get or create a feed instance."""
        if name not in self._feeds:
            feed_class = FEED_REGISTRY.get(name)
            if not feed_class:
                print(f"[ContentFeeds] Unknown feed type: {name}")
                return None
            self._feeds[name] = feed_class(config or {})
        return self._feeds[name]
    
    async def close(self):
        """Close all feed HTTP clients."""
        for feed in self._feeds.values():
            await feed.close()
        self._feeds.clear()
    
    def get_enabled_feeds(self) -> List[Dict]:
        """Get all enabled content feeds from database."""
        try:
            result = self.db.table("content_feeds").select("*").eq("enabled", True).execute()
            return result.data or []
        except Exception as e:
            print(f"[ContentFeeds] Error fetching feeds: {e}")
            return []
    
    def get_all_feeds(self) -> List[Dict]:
        """Get all content feeds (enabled and disabled)."""
        try:
            result = self.db.table("content_feeds").select("*").order("name").execute()
            return result.data or []
        except Exception as e:
            print(f"[ContentFeeds] Error fetching feeds: {e}")
            return []
    
    def should_fetch(self, feed: Dict) -> bool:
        """Check if enough time has passed since last fetch."""
        last_fetched = feed.get("last_fetched_at")
        if not last_fetched:
            return True
        
        try:
            if isinstance(last_fetched, str):
                last_dt = datetime.fromisoformat(last_fetched.replace("Z", "+00:00"))
            else:
                last_dt = last_fetched
            
            interval_hours = feed.get("fetch_interval_hours", 6.0)
            next_fetch = last_dt + timedelta(hours=interval_hours)
            return datetime.now(timezone.utc) >= next_fetch
        except Exception:
            return True
    
    async def fetch_feed(self, feed: Dict, force: bool = False) -> Dict[str, Any]:
        """
        Fetch a single feed and store new items.
        
        Returns: {success, items_found, items_new, error}
        """
        feed_id = feed["id"]
        feed_name = feed["name"]
        
        # Check if we should fetch
        if not force and not self.should_fetch(feed):
            return {
                "success": True,
                "items_found": 0,
                "items_new": 0,
                "skipped": True,
                "reason": "Not due for fetch yet",
            }
        
        # Get feed instance
        config = feed.get("config") or {}
        feed_instance = self._get_feed_instance(feed_name, config)
        if not feed_instance:
            return {
                "success": False,
                "error": f"Unknown feed type: {feed_name}",
            }
        
        start_time = time.time()
        
        try:
            # Fetch new content
            result = await feed_instance.fetch(
                last_item_id=feed.get("last_item_id"),
                etag=feed.get("etag"),
                last_modified=feed.get("last_modified"),
            )
            
            items = result["items"]
            items_found = len(items)
            items_new = 0
            
            # Store items in database
            for item in items:
                stored = await self._store_content_item(feed_id, item)
                if stored:
                    items_new += 1
            
            # Update feed status
            update_data = {
                "last_fetched_at": datetime.now(timezone.utc).isoformat(),
                "last_item_count": items_found,
                "consecutive_errors": 0,
                "last_error": None,
                "total_items_fetched": (feed.get("total_items_fetched") or 0) + items_found,
            }
            
            if result.get("last_item_id"):
                update_data["last_item_id"] = result["last_item_id"]
            if result.get("etag"):
                update_data["etag"] = result["etag"]
            if result.get("last_modified"):
                update_data["last_modified"] = result["last_modified"]
            
            self.db.table("content_feeds").update(update_data).eq("id", feed_id).execute()
            
            duration_ms = int((time.time() - start_time) * 1000)
            print(f"[ContentFeeds] {feed_name}: {items_new} new / {items_found} found ({duration_ms}ms)")
            
            # Broadcast event
            self._broadcast({
                "type": "content_feed_fetched",
                "feed": feed_name,
                "items_new": items_new,
            })
            
            return {
                "success": True,
                "items_found": items_found,
                "items_new": items_new,
                "not_modified": result.get("not_modified", False),
                "duration_ms": duration_ms,
            }
            
        except Exception as e:
            error_msg = str(e)
            print(f"[ContentFeeds] Error fetching {feed_name}: {error_msg}")
            
            # Update error status
            self.db.table("content_feeds").update({
                "consecutive_errors": (feed.get("consecutive_errors") or 0) + 1,
                "last_error": error_msg[:500],
                "last_error_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", feed_id).execute()
            
            return {
                "success": False,
                "error": error_msg,
            }
    
    async def _store_content_item(self, feed_id: int, item: ContentItem) -> bool:
        """
        Store a content item in the database.
        
        Returns True if new item was stored, False if duplicate.
        """
        try:
            # Check if item already exists
            existing = self.db.table("content_items").select("id").eq(
                "feed_id", feed_id
            ).eq("external_id", item.external_id).limit(1).execute()
            
            if existing.data:
                return False  # Duplicate
            
            # Insert new item
            insert_data = {
                "feed_id": feed_id,
                "external_id": item.external_id,
                "content_type": item.content_type,
                "title": item.title,
                "content": item.content,
                "image_url": item.image_url,
                "source_url": item.source_url,
                "author": item.author,
                "tags": item.tags or [],
                "meta_json": item.meta_json or {},
            }
            
            if item.published_at:
                insert_data["published_at"] = item.published_at.isoformat()
            
            self.db.table("content_items").insert(insert_data).execute()
            return True
            
        except Exception as e:
            print(f"[ContentFeeds] Error storing item {item.external_id}: {e}")
            return False
    
    async def fetch_all(self, force: bool = False) -> Dict[str, Any]:
        """
        Fetch all enabled feeds.
        
        Returns: {feeds_checked, total_items_new, results: {...}}
        """
        feeds = self.get_enabled_feeds()
        results = {}
        total_new = 0
        
        for feed in feeds:
            result = await self.fetch_feed(feed, force=force)
            results[feed["name"]] = result
            if result.get("success"):
                total_new += result.get("items_new", 0)
        
        return {
            "feeds_checked": len(feeds),
            "total_items_new": total_new,
            "results": results,
        }
    
    def get_recent_items(self, limit: int = 50, content_type: str = None, 
                         feed_name: str = None, unprocessed_only: bool = False) -> List[Dict]:
        """Get recent content items with optional filters."""
        try:
            query = self.db.table("content_items").select(
                "*, content_feeds!inner(name, description)"
            ).order("fetched_at", desc=True).limit(limit)
            
            if content_type:
                query = query.eq("content_type", content_type)
            
            if feed_name:
                query = query.eq("content_feeds.name", feed_name)
            
            if unprocessed_only:
                query = query.is_("ingested_to_link_id", "null")
            
            result = query.execute()
            return result.data or []
        except Exception as e:
            print(f"[ContentFeeds] Error getting recent items: {e}")
            return []
    
    async def ingest_item_as_link(self, item_id: int) -> Optional[int]:
        """
        Convert a content item to a link in the main links table.
        
        Returns the new link ID or None on failure.
        """
        try:
            # Get the item
            item_resp = self.db.table("content_items").select(
                "*, content_feeds(name)"
            ).eq("id", item_id).execute()
            
            if not item_resp.data:
                return None
            
            item = item_resp.data[0]
            
            if item.get("ingested_to_link_id"):
                return item["ingested_to_link_id"]  # Already ingested
            
            # Build link data
            feed_name = item.get("content_feeds", {}).get("name", "unknown")
            source_url = item.get("source_url") or item.get("image_url") or ""
            
            if not source_url:
                print(f"[ContentFeeds] Cannot ingest item {item_id}: no URL")
                return None
            
            link_data = {
                "url": source_url,
                "title": item.get("title") or f"{item.get('content_type', 'content').title()} from {feed_name}",
                "description": item.get("content"),
                "meta_json": {
                    "content_feed": feed_name,
                    "content_type": item.get("content_type"),
                    "author": item.get("author"),
                    "image_url": item.get("image_url"),
                    "original_tags": item.get("tags"),
                    **item.get("meta_json", {}),
                },
                "processing_status": "new",
                "processing_priority": 0,  # Low priority for content items
            }
            
            # Insert as link
            link_resp = self.db.table("links").insert(link_data).execute()
            if not link_resp.data:
                return None
            
            link_id = link_resp.data[0]["id"]
            
            # Mark item as ingested
            self.db.table("content_items").update({
                "ingested_to_link_id": link_id,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", item_id).execute()
            
            return link_id
            
        except Exception as e:
            print(f"[ContentFeeds] Error ingesting item {item_id}: {e}")
            return None


class ContentFeedScheduler:
    """
    Background scheduler for periodic content feed fetching.
    
    Similar to GatherScheduler but for content feeds.
    """
    
    def __init__(self, manager: ContentFeedManager, check_interval_minutes: float = 30.0):
        self.manager = manager
        self.check_interval_minutes = check_interval_minutes
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._last_check_time = 0.0
    
    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status for admin display."""
        now = time.time()
        next_check = self._last_check_time + (self.check_interval_minutes * 60) if self._last_check_time else now
        
        return {
            "running": self.running,
            "check_interval_minutes": self.check_interval_minutes,
            "last_check_time": self._last_check_time,
            "seconds_until_next": max(0, round(next_check - now)),
        }
    
    def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        print(f"[ContentFeedScheduler] Started (interval: {self.check_interval_minutes}min)")
    
    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        print("[ContentFeedScheduler] Stopped")
    
    async def _loop(self):
        """Main scheduler loop."""
        while self.running:
            try:
                now = time.time()
                minutes_since_last = (now - self._last_check_time) / 60
                
                if minutes_since_last >= self.check_interval_minutes:
                    print("[ContentFeedScheduler] Running scheduled fetch...")
                    await self.manager.fetch_all()
                    self._last_check_time = time.time()
                
                # Check every 5 minutes
                await asyncio.sleep(5 * 60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ContentFeedScheduler] Error: {e}")
                await asyncio.sleep(60)
