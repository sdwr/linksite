"""
RSS Gatherer Module — Fetch links from HN and Reddit RSS feeds

No auth needed, no rate limits. These are public RSS feeds.

Usage:
    from gatherer import RSSGatherer
    gatherer = RSSGatherer(supabase_client)
    await gatherer.gather_hn()
    await gatherer.gather_reddit()
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, Callable
from urllib.parse import urlparse
import feedparser
import httpx


# RSS Feed URLs
HN_RSS = "https://hnrss.org/frontpage"  # HN front page via hnrss.org
REDDIT_RSS = "https://www.reddit.com/r/all/hot/.rss"  # Reddit all/hot


class RSSGatherer:
    """Fetches links from RSS feeds and ingests them into the database."""

    def __init__(self, db, broadcast_fn: Callable = None):
        self.db = db
        self._broadcast = broadcast_fn or (lambda e: None)
        self._http_client = None

    async def _get_client(self):
        """Lazy-init async HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": "linksite-gatherer/0.1 (+https://linksite-dev-bawuw.sprites.app)"
                },
                follow_redirects=True,
            )
        return self._http_client

    # --------------------------------------------------------
    # HN Gathering
    # --------------------------------------------------------

    async def gather_hn_links(self) -> list[dict]:
        """
        Fetch HN front page via RSS.
        Returns list of {url, title, source, hn_link, hn_comments_url}.
        """
        client = await self._get_client()

        try:
            response = await client.get(HN_RSS)
            response.raise_for_status()
            feed_content = response.text
        except Exception as e:
            print(f"[Gatherer] Error fetching HN RSS: {e}")
            return []

        feed = feedparser.parse(feed_content)
        links = []

        for entry in feed.entries:
            # hnrss.org entries have:
            # - title: the HN post title
            # - link: the actual URL being linked to (or HN comments page for "Show HN", etc)
            # - comments: URL to the HN comments page
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            comments_url = entry.get("comments", "").strip()

            if not link or not title:
                continue

            # Skip HN internal links (like "Show HN" posts that link to HN itself)
            parsed = urlparse(link)
            if parsed.netloc in ("news.ycombinator.com", "www.news.ycombinator.com"):
                # This is a self-post or discussion, skip it
                continue

            links.append({
                "url": link,
                "title": title,
                "source": "hn",
                "hn_comments_url": comments_url,
            })

        print(f"[Gatherer] Fetched {len(links)} links from HN")
        return links

    # --------------------------------------------------------
    # Reddit Gathering
    # --------------------------------------------------------

    async def gather_reddit_links(self) -> list[dict]:
        """
        Fetch Reddit /r/all/hot via RSS.
        IMPORTANT: Only include actual link posts, not self/text posts.
        
        Returns list of {url, title, source, subreddit, reddit_comments_url}.
        """
        client = await self._get_client()

        try:
            response = await client.get(REDDIT_RSS)
            response.raise_for_status()
            feed_content = response.text
        except Exception as e:
            print(f"[Gatherer] Error fetching Reddit RSS: {e}")
            return []

        feed = feedparser.parse(feed_content)
        links = []

        for entry in feed.entries:
            # Reddit RSS entries:
            # - title: post title
            # - link: link to reddit comments page
            # - content[0].value: HTML content containing the actual link for link posts
            title = entry.get("title", "").strip()
            reddit_link = entry.get("link", "").strip()  # This is the reddit comments URL

            if not title:
                continue

            # Extract the actual external link from the content
            # For link posts, the content contains: [link] [comments]
            # For self posts, it only has [comments]
            content_list = entry.get("content", [])
            if not content_list:
                continue

            content_html = content_list[0].get("value", "") if content_list else ""

            # Parse to find external link
            external_url = self._extract_reddit_external_link(content_html, reddit_link)
            
            if not external_url:
                # This is a self post (no external link), skip it
                continue

            # Extract subreddit from the reddit_link
            subreddit = self._extract_subreddit(reddit_link)

            links.append({
                "url": external_url,
                "title": title,
                "source": "reddit",
                "subreddit": subreddit,
                "reddit_comments_url": reddit_link,
            })

        print(f"[Gatherer] Fetched {len(links)} links from Reddit")
        return links

    def _extract_reddit_external_link(self, content_html: str, reddit_link: str) -> Optional[str]:
        """
        Extract the external link from Reddit RSS content HTML.
        
        Link posts have format like:
        <a href="https://external.url">...</a> ... <a href="https://reddit.com/...">comments</a>
        
        Self posts only have the reddit link (no external URL).
        """
        from bs4 import BeautifulSoup

        if not content_html:
            return None

        soup = BeautifulSoup(content_html, "html.parser")
        all_links = soup.find_all("a", href=True)

        for link in all_links:
            href = link["href"]
            # Skip reddit internal links
            parsed = urlparse(href)
            if parsed.netloc in (
                "reddit.com", "www.reddit.com",
                "old.reddit.com", "new.reddit.com",
                "i.redd.it", "v.redd.it",  # Reddit media hosting
                "preview.redd.it",
            ):
                continue
            # This is an external link
            return href

        return None

    def _extract_subreddit(self, reddit_url: str) -> str:
        """Extract subreddit name from a reddit URL."""
        # URL format: https://www.reddit.com/r/SUBREDDIT/comments/...
        import re
        match = re.search(r'/r/([^/]+)', reddit_url)
        return match.group(1) if match else "unknown"

    # --------------------------------------------------------
    # Ingestion
    # --------------------------------------------------------

    async def ingest_gathered_links(self, links: list[dict], source: str) -> dict:
        """
        Ingest gathered links into the database.
        
        For each link:
        - Check if URL already exists (skip if so)
        - Insert with processing_status='new', processing_priority=1
        - Track metrics for job_run logging
        
        Returns: {items_found, items_new, items_skipped, errors}
        """
        items_found = len(links)
        items_new = 0
        items_skipped = 0
        errors = []

        for link_data in links:
            url = link_data.get("url")
            if not url:
                continue

            try:
                # Check if URL already exists
                existing = self.db.table("links").select("id").eq("url", url).limit(1).execute()
                
                if existing.data:
                    items_skipped += 1
                    continue

                # Build metadata
                meta_json = {
                    "gather_source": source,
                }
                
                if link_data.get("hn_comments_url"):
                    meta_json["hn_comments_url"] = link_data["hn_comments_url"]
                if link_data.get("reddit_comments_url"):
                    meta_json["reddit_comments_url"] = link_data["reddit_comments_url"]
                if link_data.get("subreddit"):
                    meta_json["subreddit"] = link_data["subreddit"]

                # Insert new link
                insert_data = {
                    "url": url,
                    "title": link_data.get("title", ""),
                    "meta_json": meta_json,
                    "processing_status": "new",
                    "processing_priority": 1,  # High priority for gathered links
                }

                self.db.table("links").insert(insert_data).execute()
                items_new += 1

            except Exception as e:
                error_msg = f"Error ingesting {url}: {str(e)}"
                print(f"[Gatherer] {error_msg}")
                errors.append(error_msg)

        print(f"[Gatherer] Ingested: {items_new} new, {items_skipped} skipped, {len(errors)} errors")
        return {
            "items_found": items_found,
            "items_new": items_new,
            "items_skipped": items_skipped,
            "errors": errors,
        }

    # --------------------------------------------------------
    # Job Run Logging
    # --------------------------------------------------------

    def log_job_run(self, job_type: str, source: str, results: dict, duration_ms: int) -> dict:
        """
        Log a gather job run to the job_runs table.
        
        Returns the created job_run record.
        """
        try:
            job_data = {
                "job_type": job_type,
                "source": source,
                "items_found": results.get("items_found", 0),
                "items_new": results.get("items_new", 0),
                "items_skipped": results.get("items_skipped", 0),
                "errors": results.get("errors", []),
                "duration_ms": duration_ms,
                "status": "completed" if not results.get("errors") else "completed_with_errors",
            }

            resp = self.db.table("job_runs").insert(job_data).execute()
            return resp.data[0] if resp.data else job_data

        except Exception as e:
            print(f"[Gatherer] Error logging job run: {e}")
            return {"error": str(e)}

    # --------------------------------------------------------
    # High-level gather methods
    # --------------------------------------------------------

    async def gather_hn(self) -> dict:
        """
        Full HN gather: fetch, ingest, log.
        Returns job run summary.
        """
        start_time = time.time()

        links = await self.gather_hn_links()
        results = await self.ingest_gathered_links(links, "hn")

        duration_ms = int((time.time() - start_time) * 1000)
        job_run = self.log_job_run("gather", "hn", results, duration_ms)

        # Broadcast event
        self._broadcast({
            "type": "gather_complete",
            "source": "hn",
            "items_new": results["items_new"],
        })

        return {
            "source": "hn",
            "job_run": job_run,
            **results,
        }

    async def gather_reddit(self) -> dict:
        """
        Full Reddit gather: fetch, ingest, log.
        Returns job run summary.
        """
        start_time = time.time()

        links = await self.gather_reddit_links()
        results = await self.ingest_gathered_links(links, "reddit")

        duration_ms = int((time.time() - start_time) * 1000)
        job_run = self.log_job_run("gather", "reddit", results, duration_ms)

        # Broadcast event
        self._broadcast({
            "type": "gather_complete",
            "source": "reddit",
            "items_new": results["items_new"],
        })

        return {
            "source": "reddit",
            "job_run": job_run,
            **results,
        }

    async def gather_all(self) -> dict:
        """
        Gather from all sources (HN + Reddit).
        Returns combined results.
        """
        hn_result = await self.gather_hn()
        reddit_result = await self.gather_reddit()

        return {
            "hn": hn_result,
            "reddit": reddit_result,
            "total_new": hn_result["items_new"] + reddit_result["items_new"],
        }

    async def close(self):
        """Clean up HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# --------------------------------------------------------
# Scheduler Integration
# --------------------------------------------------------

class GatherScheduler:
    """
    Background scheduler for periodic gathering.
    
    Integrates with the Director's tick loop or runs standalone.
    """

    def __init__(self, gatherer: RSSGatherer, interval_hours: float = 4.0):
        self.gatherer = gatherer
        self.interval_hours = interval_hours
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._last_gather_time = 0.0

    def start(self):
        """Start the gather scheduler."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        print(f"[GatherScheduler] Started (interval: {self.interval_hours}h)")

    def stop(self):
        """Stop the gather scheduler."""
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        print("[GatherScheduler] Stopped")

    async def _loop(self):
        """Main scheduler loop."""
        while self.running:
            try:
                now = time.time()
                hours_since_last = (now - self._last_gather_time) / 3600

                if hours_since_last >= self.interval_hours:
                    print("[GatherScheduler] Running scheduled gather...")
                    await self.gatherer.gather_all()
                    self._last_gather_time = time.time()

                # Check every 15 minutes
                await asyncio.sleep(15 * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[GatherScheduler] Error: {e}")
                await asyncio.sleep(60)  # Wait a minute on error

    def should_gather(self) -> bool:
        """Check if enough time has passed since last gather."""
        now = time.time()
        hours_since_last = (now - self._last_gather_time) / 3600
        return hours_since_last >= self.interval_hours
