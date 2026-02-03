"""
Scratchpad API — link saving, notes, tags, related links, browse.
Import and mount on the FastAPI app from main.py.
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import random
import os
from urllib.parse import urlparse
import math
import threading
import httpx
from datetime import datetime as dt_cls
import time as _time

router = APIRouter()

# Will be set by main.py when mounting
supabase = None
ingest_module = None

def init(sb_client, ingest_mod):
    global supabase, ingest_module
    supabase = sb_client
    ingest_module = ingest_mod


# ============================================================
# Reddit OAuth API
# ============================================================

_reddit_token_cache = {
    "access_token": None,
    "expires_at": 0,
}

_reddit_stats = {
    "last_call_time": 0,
    "total_calls": 0,
    "last_error": None,
    "last_error_time": None,
    "token_refreshes": 0,
    "last_search_time": None,
    "searches": 0,
    "resolves": 0,
    "started_at": _time.time(),
}

_REDDIT_MIN_INTERVAL = 1.0  # min seconds between Reddit API calls


def _get_reddit_user_agent():
    username = os.environ.get("REDDIT_USERNAME", "AMA_ABOUT_DAN_JUICE")
    return f"LinkCompass:v1.0 (by /u/{username})"


def _get_reddit_token():
    """Get a valid Reddit OAuth token, refreshing if needed."""
    now = _time.time()
    if _reddit_token_cache["access_token"] and now < _reddit_token_cache["expires_at"] - 60:
        return _reddit_token_cache["access_token"]

    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        _reddit_stats["last_error"] = "Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET env vars"
        _reddit_stats["last_error_time"] = _time.time()
        print("[Reddit] Missing credentials in env")
        return None

    try:
        resp = httpx.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": _get_reddit_user_agent()},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _reddit_token_cache["access_token"] = data["access_token"]
            _reddit_token_cache["expires_at"] = now + data.get("expires_in", 86400)
            _reddit_stats["token_refreshes"] += 1
            _reddit_stats["last_error"] = None
            print(f"[Reddit] Token refreshed, expires in {data.get('expires_in', '?')}s")
            return data["access_token"]
        else:
            err = f"Token request failed: HTTP {resp.status_code}"
            _reddit_stats["last_error"] = err
            _reddit_stats["last_error_time"] = _time.time()
            print(f"[Reddit] {err} — {resp.text[:200]}")
    except Exception as e:
        _reddit_stats["last_error"] = str(e)
        _reddit_stats["last_error_time"] = _time.time()
        print(f"[Reddit] Token error: {e}")

    return None


def _reddit_api_get(path, params=None):
    """Make an authenticated GET to Reddit OAuth API with rate limiting."""
    # Rate limit: wait if last call was too recent
    now = _time.time()
    elapsed = now - _reddit_stats["last_call_time"]
    if elapsed < _REDDIT_MIN_INTERVAL:
        _time.sleep(_REDDIT_MIN_INTERVAL - elapsed)

    token = _get_reddit_token()
    if not token:
        return None

    ua = _get_reddit_user_agent()

    try:
        resp = httpx.get(
            f"https://oauth.reddit.com{path}",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": ua,
            },
            timeout=10,
            follow_redirects=True,
        )
        _reddit_stats["last_call_time"] = _time.time()
        _reddit_stats["total_calls"] += 1

        if resp.status_code == 200:
            _reddit_stats["last_error"] = None
            return resp.json()
        elif resp.status_code == 401:
            # Token expired — clear cache and retry once
            _reddit_token_cache["access_token"] = None
            _reddit_token_cache["expires_at"] = 0
            token = _get_reddit_token()
            if token:
                resp = httpx.get(
                    f"https://oauth.reddit.com{path}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": ua,
                    },
                    timeout=10,
                    follow_redirects=True,
                )
                _reddit_stats["last_call_time"] = _time.time()
                _reddit_stats["total_calls"] += 1
                if resp.status_code == 200:
                    _reddit_stats["last_error"] = None
                    return resp.json()
            err = f"Auth failed after retry: HTTP {resp.status_code}"
            _reddit_stats["last_error"] = err
            _reddit_stats["last_error_time"] = _time.time()
            print(f"[Reddit] {err}")
        else:
            err = f"API error: HTTP {resp.status_code}"
            _reddit_stats["last_error"] = err
            _reddit_stats["last_error_time"] = _time.time()
            print(f"[Reddit] {err} — {resp.text[:200]}")
    except Exception as e:
        _reddit_stats["last_error"] = str(e)
        _reddit_stats["last_error_time"] = _time.time()
        print(f"[Reddit] API request error: {e}")

    return None


def get_reddit_api_status():
    """Return Reddit API status dict for admin display."""
    now = _time.time()
    uptime = now - _reddit_stats["started_at"]
    token_valid = (
        _reddit_token_cache["access_token"] is not None
        and now < _reddit_token_cache["expires_at"]
    )
    token_expires_in = max(0, _reddit_token_cache["expires_at"] - now) if token_valid else 0

    has_creds = bool(
        os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")
    )

    # Calculate RPM over last 60 seconds (approximate)
    rpm = (_reddit_stats["total_calls"] / uptime * 60) if uptime > 0 else 0

    return {
        "configured": has_creds,
        "token_valid": token_valid,
        "token_expires_in_sec": round(token_expires_in),
        "total_calls": _reddit_stats["total_calls"],
        "searches": _reddit_stats["searches"],
        "resolves": _reddit_stats["resolves"],
        "token_refreshes": _reddit_stats["token_refreshes"],
        "last_error": _reddit_stats["last_error"],
        "last_error_time": _reddit_stats["last_error_time"],
        "last_call_time": _reddit_stats["last_call_time"],
        "last_search_time": _reddit_stats["last_search_time"],
        "avg_rpm": round(rpm, 2),
        "uptime_sec": round(uptime),
    }


# --- Models ---

class LinkCreate(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    note: Optional[str] = None
    author: Optional[str] = "anonymous"

class LinkEdit(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

class NoteCreate(BaseModel):
    author: str = "anonymous"
    text: str
    user_id: Optional[str] = None

class TagsAdd(BaseModel):
    tags: List[str]
    author: Optional[str] = "anonymous"


# --- Helpers ---

def get_base_domain(url: str) -> str:
    """Extract base domain URL from a full URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"

def find_or_create_parent(url: str, link_id: int):
    """Find or create a parent link for the base domain."""
    parsed = urlparse(url)
    host = (parsed.netloc or '').lower()
    if host.startswith('www.'):
        host = host[4:]

    # Don't create parent for root domains
    path = parsed.path.rstrip('/')
    if not path and not parsed.query:
        return None

    # Normalized base domain URL
    base = 'https://' + host

    # Check if base domain exists
    resp = supabase.table("links").select("id").eq("url", base).execute()
    if resp.data:
        parent_id = resp.data[0]["id"]
    else:
        # Create stub entry for the domain
        stub = supabase.table("links").insert({
            "url": base,
            "title": host,
            "source": "auto-parent",
            "description": f"Parent site: {host}",
        }).execute()
        parent_id = stub.data[0]["id"] if stub.data else None

    if parent_id and parent_id != link_id:
        supabase.table("links").update({"parent_link_id": parent_id}).eq("id", link_id).execute()

    return parent_id

def ingest_link_async(link_id: int, url: str):
    """Run content extraction in background thread."""
    def _ingest():
        try:
            extractor = ingest_module.ContentExtractor()
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            result = None
            if "youtube.com" in domain or "youtu.be" in domain:
                result = extractor.extract_youtube_content(url)
            elif "bsky.app" in domain or "bsky.social" in domain:
                pass  # Skip bluesky for now
            else:
                result = extractor.extract_website_content(url)

            if result:
                update = {}

                # Title
                if result.get("title"):
                    update["title"] = result["title"]

                # Thumbnail / OG image
                if result.get("og_image"):
                    update["og_image_url"] = result["og_image"]
                if result.get("thumbnail"):
                    update["og_image_url"] = result["thumbnail"]

                # Content + Description (separate short desc from full content)
                if result.get("content"):
                    update["content"] = result["content"][:10000]
                if result.get("description"):
                    update["description"] = result["description"][:500]
                # Fallback: if no separate description, derive from content
                if not update.get("description") and update.get("content"):
                    update["description"] = update["content"][:500]

                # Meta JSON — merge new metadata with any existing
                meta = result.get("meta", {})
                if meta:
                    try:
                        current = supabase.table("links").select("meta_json").eq("id", link_id).execute()
                        existing_meta = (current.data[0].get("meta_json") or {}) if current.data else {}
                        existing_meta.update(meta)
                        update["meta_json"] = existing_meta
                    except Exception:
                        update["meta_json"] = meta

                if update:
                    supabase.table("links").update(update).eq("id", link_id).execute()
                    print(f"[Scratchpad] Ingested link {link_id}: {list(update.keys())}")

                # Generate embedding — prefer content, fall back to description
                try:
                    text = update.get("content") or update.get("description") or ""
                    if text:
                        vectorizer = ingest_module.TextVectorizer()
                        vec = vectorizer.vectorize(text[:2000])
                        supabase.table("links").update({"content_vector": vec}).eq("id", link_id).execute()
                        print(f"[Scratchpad] Vectorized link {link_id}")
                except Exception as ve:
                    print(f"[Scratchpad] Vectorize error for {link_id}: {ve}")

            # Set parent link
            find_or_create_parent(url, link_id)

        except Exception as e:
            print(f"[Scratchpad] Ingest error for {link_id}: {e}")

    thread = threading.Thread(target=_ingest, daemon=True)
    thread.start()
    # Also fetch external discussions in background
    def _ext_disc():
        import time
        time.sleep(2)  # small delay to let ingestion start first
        fetch_and_save_external_discussions(link_id, url)
        check_reverse_lookup(url, link_id)
    ext_thread = threading.Thread(target=_ext_disc, daemon=True)
    ext_thread.start()


def get_link_tags(link_id: int) -> list:
    """Get tags for a link."""
    resp = supabase.table("link_tags").select("tag_id").eq("link_id", link_id).execute()
    if not resp.data:
        return []
    tag_ids = [r["tag_id"] for r in resp.data]
    tags_resp = supabase.table("tags").select("id, name, slug").in_("id", tag_ids).execute()
    return tags_resp.data or []

def get_link_notes(link_id: int) -> list:
    """Get notes for a link, enriched with user display names."""
    resp = supabase.table("notes").select("*").eq("link_id", link_id).order("created_at", desc=True).execute()
    notes = resp.data or []
    # Batch-fetch user display names
    user_ids = list(set(n.get("user_id") for n in notes if n.get("user_id")))
    user_map = {}
    if user_ids:
        try:
            users_resp = supabase.table("users").select("id, display_name").in_("id", user_ids).execute()
            for u in (users_resp.data or []):
                user_map[u["id"]] = u.get("display_name", "Anonymous")
        except Exception:
            pass
    # Attach display_name to each note
    for note in notes:
        uid = note.get("user_id")
        if uid and uid in user_map:
            note["display_name"] = user_map[uid]
        else:
            note["display_name"] = note.get("author", "anonymous")
    return notes

def get_related_links(link_id: int, limit: int = 10) -> list:
    """Find related links via parent or feed."""
    link_resp = supabase.table("links").select("parent_link_id, feed_id").eq("id", link_id).execute()
    if not link_resp.data:
        return []

    link_data = link_resp.data[0]
    related = []

    # Same parent
    if link_data.get("parent_link_id"):
        r = supabase.table("links").select("id, url, title, og_image_url, description").eq(
            "parent_link_id", link_data["parent_link_id"]
        ).neq("id", link_id).limit(limit).execute()
        related.extend(r.data or [])

    # Same feed
    if link_data.get("feed_id") and len(related) < limit:
        r = supabase.table("links").select("id, url, title, og_image_url, description").eq(
            "feed_id", link_data["feed_id"]
        ).neq("id", link_id).limit(limit - len(related)).execute()
        for item in (r.data or []):
            if item["id"] not in [x["id"] for x in related]:
                related.append(item)

    return related[:limit]


def enrich_link(link: dict) -> dict:
    """Add tags, notes, related, parent to a link dict."""
    lid = link["id"]
    link["tags"] = get_link_tags(lid)
    link["notes"] = get_link_notes(lid)
    link["related"] = get_related_links(lid, 5)

    # Parent
    if link.get("parent_link_id"):
        p = supabase.table("links").select("id, url, title").eq("id", link["parent_link_id"]).execute()
        link["parent"] = p.data[0] if p.data else None
    else:
        link["parent"] = None

    link["note_count"] = len(link["notes"])
    link["external_discussions"] = get_external_discussions(link["id"])
    return link


def _add_tags(link_id: int, tag_names: list, author: str = "anonymous"):
    """Add tags to a link, creating tag entries if needed."""
    for name in tag_names:
        slug = name.lower().strip().replace(" ", "-")
        if not slug:
            continue
        tag_resp = supabase.table("tags").select("id").eq("slug", slug).execute()
        if tag_resp.data:
            tag_id = tag_resp.data[0]["id"]
        else:
            new_tag = supabase.table("tags").insert({"name": name.strip(), "slug": slug}).execute()
            tag_id = new_tag.data[0]["id"]
        try:
            supabase.table("link_tags").insert({
                "link_id": link_id, "tag_id": tag_id, "added_by": author
            }).execute()
        except Exception:
            pass  # Already exists


# --- Helpers ---

LINKSITE_BASE_URL = "https://linksite-dev-bawuw.sprites.app"

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




# --- External Discussions ---

def find_external_discussions(url: str) -> list:
    """Query HN Algolia and Reddit (OAuth) for discussions about this URL."""
    results = []
    
    # Strip scheme for better search matching
    from urllib.parse import urlparse as _urlparse
    search_url = url
    _parsed = _urlparse(url)
    if _parsed.scheme:
        search_url = url.split("://", 1)[1] if "://" in url else url
    
    # 1. Hacker News via Algolia
    try:
        resp = httpx.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": search_url, "restrictSearchableAttributes": "url", "hitsPerPage": 20},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            data = resp.json()
            for hit in data.get("hits", []):
                ext_created = None
                if hit.get("created_at"):
                    try:
                        ext_created = hit["created_at"]
                    except Exception:
                        pass
                results.append({
                    "platform": "hackernews",
                    "external_url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                    "external_id": hit.get("objectID", ""),
                    "title": hit.get("title") or f"HN Discussion ({hit.get('objectID', '')})",
                    "score": hit.get("points", 0) or 0,
                    "num_comments": hit.get("num_comments", 0) or 0,
                    "subreddit": None,
                    "external_created_at": ext_created,
                })
        print(f"[ExtDisc] HN returned {len(results)} results for {url}")
    except Exception as e:
        print(f"[ExtDisc] HN error for {url}: {e}")
    
    # 2. Reddit via OAuth API
    try:
        _reddit_stats["last_search_time"] = _time.time()
        _reddit_stats["searches"] += 1

        data = _reddit_api_get("/search", params={
            "q": f"url:{url}",
            "sort": "top",
            "limit": 20,
            "type": "link",
        })
        if data:
            children = data.get("data", {}).get("children", [])
            for child in children:
                post = child.get("data", {})
                ext_created = None
                if post.get("created_utc"):
                    try:
                        ext_created = datetime.fromtimestamp(
                            post["created_utc"], tz=timezone.utc
                        ).isoformat()
                    except Exception:
                        pass
                results.append({
                    "platform": "reddit",
                    "external_url": f"https://www.reddit.com{post.get('permalink', '')}",
                    "external_id": post.get("id", ""),
                    "title": post.get("title", "Reddit Discussion"),
                    "score": post.get("score", 0) or 0,
                    "num_comments": post.get("num_comments", 0) or 0,
                    "subreddit": post.get("subreddit", ""),
                    "external_created_at": ext_created,
                })
            print(f"[ExtDisc] Reddit OAuth returned {len(children)} results for {url}")
        else:
            print(f"[ExtDisc] Reddit OAuth returned no data for {url}")
    except Exception as e:
        print(f"[ExtDisc] Reddit error for {url}: {e}")
    
    return results


def save_external_discussions(link_id: int, discussions: list):
    """Save external discussions to DB, upsert by (link_id, platform, external_id)."""
    saved = 0
    for d in discussions:
        try:
            row = {
                "link_id": link_id,
                "platform": d["platform"],
                "external_url": d["external_url"],
                "external_id": d.get("external_id", ""),
                "title": d.get("title", ""),
                "score": d.get("score", 0),
                "num_comments": d.get("num_comments", 0),
                "subreddit": d.get("subreddit"),
                "external_created_at": d.get("external_created_at"),
            }
            supabase.table("external_discussions").upsert(
                row,
                on_conflict="link_id,platform,external_id"
            ).execute()
            saved += 1
        except Exception as e:
            print(f"[ExtDisc] Save error: {e}")
    print(f"[ExtDisc] Saved {saved}/{len(discussions)} discussions for link {link_id}")
    return saved


def get_external_discussions(link_id: int) -> list:
    """Fetch saved external discussions for a link."""
    try:
        resp = supabase.table("external_discussions").select("*").eq(
            "link_id", link_id
        ).order("num_comments", desc=True).execute()
        return resp.data or []
    except Exception as e:
        print(f"[ExtDisc] Fetch error for link {link_id}: {e}")
        return []


def fetch_and_save_external_discussions(link_id: int, url: str):
    """Find and save external discussions (run in background thread)."""
    try:
        discussions = find_external_discussions(url)
        if discussions:
            save_external_discussions(link_id, discussions)
    except Exception as e:
        print(f"[ExtDisc] fetch_and_save error for link {link_id}: {e}")


def resolve_hn_url(hn_url: str) -> str:
    """Given an HN item URL, find the original URL it points to."""
    try:
        import re
        match = re.search(r'id=(\d+)', hn_url)
        if not match:
            return None
        item_id = match.group(1)
        resp = httpx.get(f"https://hn.algolia.com/api/v1/items/{item_id}", timeout=10, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("url")
    except Exception as e:
        print(f"[ExtDisc] HN resolve error: {e}")
    return None


def resolve_reddit_url(reddit_url: str) -> str:
    """Given a Reddit post URL, find the original URL it links to (via OAuth API)."""
    try:
        _reddit_stats["resolves"] += 1

        # Extract the Reddit post path from the URL
        parsed = urlparse(reddit_url)
        path = parsed.path.rstrip("/")
        if not path:
            return None

        # Use OAuth API to get post details
        # The path should be like /r/subreddit/comments/id/title
        data = _reddit_api_get(path + ".json")
        if data and isinstance(data, list) and len(data) > 0:
            children = data[0].get("data", {}).get("children", [])
            if children:
                post_data = children[0].get("data", {})
                url = post_data.get("url", "")
                # Skip self posts and reddit links
                if url and not url.startswith("https://www.reddit.com") and not post_data.get("is_self"):
                    print(f"[ExtDisc] Reddit resolve: {reddit_url} -> {url}")
                    return url
        
        # Fallback: try the public .json endpoint (no auth)
        print(f"[ExtDisc] Reddit OAuth resolve returned no URL, trying public fallback for {reddit_url}")
        resp = httpx.get(
            reddit_url + ".json",
            headers={"User-Agent": _get_reddit_user_agent()},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                post_data = data[0].get("data", {}).get("children", [{}])[0].get("data", {})
                url = post_data.get("url", "")
                if url and not url.startswith("https://www.reddit.com") and not post_data.get("is_self"):
                    return url
    except Exception as e:
        _reddit_stats["last_error"] = f"Resolve error: {e}"
        _reddit_stats["last_error_time"] = _time.time()
        print(f"[ExtDisc] Reddit resolve error: {e}")
    return None


def check_reverse_lookup(url: str, link_id: int):
    """If URL is an HN or Reddit link, find the original URL and save it."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    original_url = None
    is_discussion_platform = False
    
    if "news.ycombinator.com" in domain:
        is_discussion_platform = True
        original_url = resolve_hn_url(url)
    elif "reddit.com" in domain and "/comments/" in url:
        is_discussion_platform = True
        original_url = resolve_reddit_url(url)
    
    # Mark HN/Reddit links as discussion refs so they're filtered from browse/random
    if is_discussion_platform:
        supabase.table("links").update({"source": "discussion-ref"}).eq("id", link_id).execute()
        print(f"[ExtDisc] Marked link {link_id} as discussion-ref")
    
    if original_url:
        # Normalize the resolved URL before checking/creating
        original_url = normalize_url(original_url)
        
        # Check if original URL already exists
        existing = supabase.table("links").select("id").eq("url", original_url).execute()
        if existing.data:
            original_link_id = existing.data[0]["id"]
            # Link the HN/Reddit link as a child of the original
            supabase.table("links").update({"parent_link_id": original_link_id}).eq("id", link_id).execute()
            print(f"[ExtDisc] Reverse: linked {link_id} -> existing {original_link_id} ({original_url})")
        else:
            # Create the original link (handle race condition / normalization mismatch)
            try:
                resp = supabase.table("links").insert({
                    "url": original_url,
                    "source": "reverse-lookup",
                    "submitted_by": "auto",
                }).execute()
                if resp.data:
                    original_link_id = resp.data[0]["id"]
                else:
                    return
            except Exception as insert_err:
                # Likely a unique constraint violation - URL exists with slightly different normalization
                print(f"[ExtDisc] Insert failed (probably dup), retrying lookup: {insert_err}")
                retry = supabase.table("links").select("id").eq("url", original_url).execute()
                if not retry.data:
                    # Try with/without trailing slash
                    alt_url = original_url.rstrip('/') + '/' if not original_url.endswith('/') else original_url.rstrip('/')
                    retry = supabase.table("links").select("id").eq("url", alt_url).execute()
                if retry.data:
                    original_link_id = retry.data[0]["id"]
                    supabase.table("links").update({"parent_link_id": original_link_id}).eq("id", link_id).execute()
                    print(f"[ExtDisc] Reverse: linked {link_id} -> existing {original_link_id} (found on retry)")
                else:
                    print(f"[ExtDisc] Could not find or create link for {original_url}")
                return
            if original_link_id:
                # Set parent
                supabase.table("links").update({"parent_link_id": original_link_id}).eq("id", link_id).execute()
                print(f"[ExtDisc] Reverse: created {original_link_id} ({original_url}) as parent of {link_id}")
                # Trigger ingestion + external discussion lookup for the original
                ingest_link_async(original_link_id, original_url)
                # Also find discussions for the original URL
                def _disc():
                    fetch_and_save_external_discussions(original_link_id, original_url)
                threading.Thread(target=_disc, daemon=True).start()


# --- API Routes ---

@router.api_route("/api/check", methods=["GET", "POST"])
async def api_check_link(url: str = "", comments: int = 5):
    """
    Bot-friendly endpoint. Check a URL — create if new, return compact summary.
    Always triggers ingestion if title is missing.
    
    Query params:
        url: the URL to check/save (bare domains like example.com accepted)
        comments: max comments to return (default 5)
    """
    url = normalize_url(url)
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    existing = supabase.table("links").select(
        "id, url, title, direct_score, created_at, parent_link_id"
    ).eq("url", url).execute()

    is_new = False
    if existing.data:
        link = existing.data[0]
    else:
        resp = supabase.table("links").insert({
            "url": url,
            "source": "agent",
            "submitted_by": "bot",
        }).execute()
        if not resp.data:
            raise HTTPException(status_code=500, detail="Failed to create link")
        link = resp.data[0]
        is_new = True

    lid = link["id"]

    # Trigger ingestion if new or title still empty
    if is_new or not link.get("title"):
        ingest_link_async(lid, url)

    domain = (urlparse(link["url"]).netloc or "")

    tags = get_link_tags(lid)
    tag_names = [t["name"] for t in tags]

    notes_resp = supabase.table("notes").select(
        "author, text, created_at"
    ).eq("link_id", lid).order("created_at", desc=True).limit(comments).execute()
    comment_list = []
    for n in (notes_resp.data or []):
        author_name = n.get("author", "anon")
        # Look up display name from user_id if available
        note_user_id = n.get("user_id")
        if note_user_id:
            try:
                user_resp = supabase.table("users").select("display_name").eq("id", note_user_id).execute()
                if user_resp.data:
                    author_name = user_resp.data[0].get("display_name", author_name)
            except Exception:
                pass
        comment_list.append({
            "author": author_name,
            "text": n.get("text", ""),
            "time": n.get("created_at", ""),
            "user_id": note_user_id,
        })

    # Fetch external discussions
    ext_disc = get_external_discussions(lid)
    ext_disc_list = [{
        "platform": d.get("platform", ""),
        "title": d.get("title", ""),
        "url": d.get("external_url", ""),
        "score": d.get("score", 0),
        "num_comments": d.get("num_comments", 0),
        "subreddit": d.get("subreddit"),
    } for d in ext_disc]

    return {
        "is_new": is_new,
        "id": lid,
        "url": link["url"],
        "title": link.get("title") or "",
        "domain": domain,
        "tags": tag_names,
        "stars": link.get("direct_score", 0) or 0,
        "comments": comment_list,
        "comment_count": len(get_link_notes(lid)),
        "web_url": f"{LINKSITE_BASE_URL}/link/{lid}",
        "external_discussions": ext_disc_list,
    }


@router.get("/api/link")
async def api_link_lookup(url: str):
    """Look up a link by URL."""
    url = normalize_url(url)
    resp = supabase.table("links").select(
        "id, url, title, description, og_image_url, screenshot_url, source, submitted_by, parent_link_id, direct_score, created_at, feed_id, meta_json"
    ).eq("url", url).execute()

    if not resp.data:
        return {"link": None}

    link = enrich_link(resp.data[0])
    return {"link": link}


@router.post("/api/link")
async def api_link_create(body: LinkCreate):
    """Save a new link. Returns existing if URL already tracked."""
    body.url = normalize_url(body.url)
    existing = supabase.table("links").select("id").eq("url", body.url).execute()
    if existing.data:
        link_id = existing.data[0]["id"]
        if body.note:
            supabase.table("notes").insert({
                "link_id": link_id, "author": body.author, "text": body.note
            }).execute()
        if body.tags:
            _add_tags(link_id, body.tags, body.author)

        full = supabase.table("links").select(
            "id, url, title, description, og_image_url, screenshot_url, source, submitted_by, parent_link_id, direct_score, created_at, feed_id, meta_json"
        ).eq("id", link_id).execute()
        return {"link": enrich_link(full.data[0]), "created": False}

    insert_data = {
        "url": body.url,
        "source": "agent",
        "submitted_by": body.author,
    }
    if body.title:
        insert_data["title"] = body.title
    if body.description:
        insert_data["description"] = body.description

    resp = supabase.table("links").insert(insert_data).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create link")

    link_id = resp.data[0]["id"]

    if body.note:
        supabase.table("notes").insert({
            "link_id": link_id, "author": body.author, "text": body.note
        }).execute()
    if body.tags:
        _add_tags(link_id, body.tags, body.author)

    ingest_link_async(link_id, body.url)

    full = supabase.table("links").select(
        "id, url, title, description, og_image_url, screenshot_url, source, submitted_by, parent_link_id, direct_score, created_at, feed_id, meta_json"
    ).eq("id", link_id).execute()
    return {"link": enrich_link(full.data[0]), "created": True}


@router.patch("/api/link/{link_id}")
async def api_link_edit(link_id: int, body: LinkEdit):
    """Edit title/description."""
    update = {}
    if body.title is not None:
        update["title"] = body.title
    if body.description is not None:
        update["description"] = body.description
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")

    supabase.table("links").update(update).eq("id", link_id).execute()
    return {"ok": True}


@router.get("/api/link/{link_id}/notes")
async def api_link_notes(link_id: int):
    return {"notes": get_link_notes(link_id)}


@router.post("/api/link/{link_id}/notes")
async def api_link_note_create(link_id: int, body: NoteCreate, request: Request):
    insert_data = {
        "link_id": link_id, "author": body.author, "text": body.text
    }
    # Attach user_id from body or from cookie
    user_id = body.user_id
    if not user_id:
        user_id = getattr(getattr(request, 'state', None), 'user_id', None)
    if user_id:
        insert_data["user_id"] = user_id
        # Also set author to display name if author is default
        if body.author in ("anonymous", "anon"):
            display_name = getattr(getattr(request, 'state', None), 'display_name', None)
            if display_name and display_name != "Anonymous":
                insert_data["author"] = display_name
    resp = supabase.table("notes").insert(insert_data).execute()
    return {"note": resp.data[0] if resp.data else None}


@router.post("/api/link/{link_id}/tags")
async def api_link_tags_add(link_id: int, body: TagsAdd):
    _add_tags(link_id, body.tags, body.author)
    return {"tags": get_link_tags(link_id)}


@router.delete("/api/link/{link_id}/tags/{slug}")
async def api_link_tag_remove(link_id: int, slug: str):
    tag_resp = supabase.table("tags").select("id").eq("slug", slug).execute()
    if tag_resp.data:
        tag_id = tag_resp.data[0]["id"]
        supabase.table("link_tags").delete().eq("link_id", link_id).eq("tag_id", tag_id).execute()
    return {"ok": True}


@router.get("/api/link/{link_id}/related")
async def api_link_related(link_id: int, limit: int = 10):
    return {"related": get_related_links(link_id, limit)}




@router.post("/api/link/{link_id}/find-discussions")
async def api_find_discussions(link_id: int):
    """Manually trigger external discussion lookup for a link."""
    link_resp = supabase.table("links").select("id, url").eq("id", link_id).execute()
    if not link_resp.data:
        raise HTTPException(status_code=404, detail="Link not found")
    url = link_resp.data[0]["url"]
    
    def _run():
        fetch_and_save_external_discussions(link_id, url)
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    
    return {"ok": True, "message": "Discussion lookup started"}


@router.get("/api/link/{link_id}/discussions")
async def api_get_discussions(link_id: int):
    """Get external discussions for a link."""
    return {"discussions": get_external_discussions(link_id)}


@router.get("/api/reddit-status")
async def api_reddit_status():
    """Get Reddit API status for admin monitoring."""
    return get_reddit_api_status()


@router.get("/api/links")
async def api_links_browse(
    tag: Optional[str] = None,
    sort: str = "recent",
    q: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
):
    """Browse/search links."""
    query = supabase.table("links").select(
        "id, url, title, description, og_image_url, screenshot_url, source, submitted_by, direct_score, created_at, parent_link_id",
        count="exact"
    )

    query = query.neq("source", "auto-parent")
    query = query.neq("source", "discussion-ref")

    if tag:
        tag_resp = supabase.table("tags").select("id").eq("slug", tag).execute()
        if tag_resp.data:
            tag_id = tag_resp.data[0]["id"]
            lt_resp = supabase.table("link_tags").select("link_id").eq("tag_id", tag_id).execute()
            link_ids = [r["link_id"] for r in (lt_resp.data or [])]
            if link_ids:
                query = query.in_("id", link_ids)
            else:
                return {"links": [], "total": 0}

    if q:
        query = query.or_(f"title.ilike.%{q}%,url.ilike.%{q}%,description.ilike.%{q}%")

    if sort == "score":
        query = query.order("direct_score", desc=True)
    else:
        query = query.order("created_at", desc=True)

    query = query.range(offset, offset + limit - 1)
    resp = query.execute()

    links = resp.data or []

    if links:
        link_ids = [link["id"] for link in links]

        # Batch fetch all link_tags (3 queries instead of N*2)
        lt_resp = supabase.table("link_tags").select("link_id, tag_id").in_("link_id", link_ids).execute()
        all_link_tags = lt_resp.data or []

        # Get unique tag IDs and batch fetch tag info
        tag_ids = list(set(lt["tag_id"] for lt in all_link_tags))
        tag_map = {}
        if tag_ids:
            tags_resp = supabase.table("tags").select("id, name, slug").in_("id", tag_ids).execute()
            for t in (tags_resp.data or []):
                tag_map[t["id"]] = t

        # Build link_id -> tags mapping
        link_tags_map = {}
        for lt in all_link_tags:
            lid = lt["link_id"]
            tid = lt["tag_id"]
            if tid in tag_map:
                link_tags_map.setdefault(lid, []).append(tag_map[tid])

        # Batch fetch note counts (one query, count client-side)
        notes_resp = supabase.table("notes").select("link_id").in_("link_id", link_ids).execute()
        note_counts = {}
        for n in (notes_resp.data or []):
            note_counts[n["link_id"]] = note_counts.get(n["link_id"], 0) + 1

        # Assign to links
        for link in links:
            link["tags"] = link_tags_map.get(link["id"], [])
            link["note_count"] = note_counts.get(link["id"], 0)

    return {"links": links, "total": resp.count or 0}

# --- Cached random link IDs ---

_random_ids_cache = {"ids": [], "ts": 0}
_RANDOM_CACHE_TTL = 60  # seconds

def _get_random_ids():
    """Return cached list of all link IDs, refreshed every 60s."""
    now = _time.time()
    if now - _random_ids_cache["ts"] > _RANDOM_CACHE_TTL or not _random_ids_cache["ids"]:
        resp = supabase.table("links").select("id").neq("source", "auto-parent").neq("source", "discussion-ref").order("id", desc=False).limit(10000).execute()
        _random_ids_cache["ids"] = [r["id"] for r in (resp.data or [])]
        _random_ids_cache["ts"] = now
    return _random_ids_cache["ids"]


@router.get("/api/random")
async def api_random_link(format: Optional[str] = None):
    """Pick a random link and redirect to its detail page. Use format=json for JSON."""
    ids = _get_random_ids()
    if not ids:
        if format == "json":
            return {"id": None, "url": "/browse"}
        return RedirectResponse(url="/browse", status_code=302)
    chosen = random.choice(ids)
    if format == "json":
        return {"id": chosen, "url": f"/link/{chosen}"}
    return RedirectResponse(url=f"/link/{chosen}", status_code=302)
