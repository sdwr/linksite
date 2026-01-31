"""
Scratchpad API — link saving, notes, tags, related links, browse.
Import and mount on the FastAPI app from main.py.
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from urllib.parse import urlparse
import math
import threading

router = APIRouter()

# Will be set by main.py when mounting
supabase = None
ingest_module = None

def init(sb_client, ingest_mod):
    global supabase, ingest_module
    supabase = sb_client
    ingest_module = ingest_mod


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
    base = get_base_domain(url)
    parsed = urlparse(url)

    # Don't create parent for root domains
    if parsed.path in ("", "/") and not parsed.query:
        return None

    # Check if base domain exists
    resp = supabase.table("links").select("id").eq("url", base).execute()
    if resp.data:
        parent_id = resp.data[0]["id"]
    else:
        # Also check without trailing slash
        resp2 = supabase.table("links").select("id").eq("url", base + "/").execute()
        if resp2.data:
            parent_id = resp2.data[0]["id"]
        else:
            # Create stub entry for the domain
            stub = supabase.table("links").insert({
                "url": base,
                "title": parsed.netloc,
                "source": "auto-parent",
                "description": f"Parent site: {parsed.netloc}",
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
                if result.get("title"):
                    update["title"] = result["title"]
                if result.get("main_text"):
                    update["content"] = result["main_text"][:10000]
                    update["description"] = result["main_text"][:500]
                if result.get("og_image"):
                    update["og_image_url"] = result["og_image"]
                if result.get("thumbnail"):
                    update["og_image_url"] = result["thumbnail"]
                if result.get("transcript"):
                    update["content"] = result["transcript"][:10000]
                    update["description"] = result["transcript"][:500]

                if update:
                    supabase.table("links").update(update).eq("id", link_id).execute()
                    print(f"[Scratchpad] Ingested link {link_id}: {list(update.keys())}")

                # Generate embedding
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


def get_link_tags(link_id: int) -> list:
    """Get tags for a link."""
    resp = supabase.table("link_tags").select("tag_id").eq("link_id", link_id).execute()
    if not resp.data:
        return []
    tag_ids = [r["tag_id"] for r in resp.data]
    tags_resp = supabase.table("tags").select("id, name, slug").in_("id", tag_ids).execute()
    return tags_resp.data or []

def get_link_notes(link_id: int) -> list:
    """Get notes for a link."""
    resp = supabase.table("notes").select("*").eq("link_id", link_id).order("created_at", desc=True).execute()
    return resp.data or []

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
    """Normalize a URL: add https:// if missing, strip www."""
    url = url.strip()
    if not url:
        return url
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    parsed = urlparse(url)
    host = parsed.netloc or ''
    if host.startswith('www.'):
        host = host[4:]
        url = parsed._replace(netloc=host).geturl()
    return url


# --- API Routes ---

@router.get("/api/check")
async def api_check_link(url: str, comments: int = 5):
    """
    Bot-friendly endpoint. Check/lookup a URL, return compact summary.
    If not found, returns is_new hint so caller can POST /api/link to create.
    
    Query params:
        url: the URL to check (bare domains like example.com accepted)
        comments: max comments to return (default 5)
    """
    url = normalize_url(url)
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    resp = supabase.table("links").select(
        "id, url, title, direct_score, created_at, parent_link_id"
    ).eq("url", url).execute()

    if not resp.data:
        return {"found": False, "url": url}

    link = resp.data[0]
    lid = link["id"]
    domain = (urlparse(link["url"]).netloc or "")

    # Tags (compact: just names)
    tags = get_link_tags(lid)
    tag_names = [t["name"] for t in tags]

    # Comments (most recent N)
    notes_resp = supabase.table("notes").select(
        "author, text, created_at"
    ).eq("link_id", lid).order("created_at", desc=True).limit(comments).execute()
    comment_list = []
    for n in (notes_resp.data or []):
        comment_list.append({
            "author": n.get("author", "anon"),
            "text": n.get("text", ""),
            "time": n.get("created_at", ""),
        })

    return {
        "found": True,
        "id": lid,
        "url": link["url"],
        "title": link.get("title") or "",
        "domain": domain,
        "tags": tag_names,
        "stars": link.get("direct_score", 0) or 0,
        "comments": comment_list,
        "comment_count": len(get_link_notes(lid)),
        "web_url": f"{LINKSITE_BASE_URL}/link/{lid}",
    }


@router.post("/api/check")
async def api_check_and_save(url: str = "", comments: int = 5):
    """
    Bot-friendly endpoint. Check a URL — create if new, return compact summary.
    Accepts url as query param or JSON body.
    
    Query params:
        url: the URL to check/save
        comments: max comments to return (default 5)
    """
    url = normalize_url(url)
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Check if exists
    existing = supabase.table("links").select(
        "id, url, title, direct_score, created_at, parent_link_id"
    ).eq("url", url).execute()

    is_new = False
    if existing.data:
        link = existing.data[0]
    else:
        # Create new
        resp = supabase.table("links").insert({
            "url": url,
            "source": "agent",
            "submitted_by": "bot",
        }).execute()
        if not resp.data:
            raise HTTPException(status_code=500, detail="Failed to create link")
        link = resp.data[0]
        is_new = True
        # Trigger async ingestion
        ingest_link_async(link["id"], url)

    lid = link["id"]
    domain = (urlparse(link["url"]).netloc or "")

    # Tags
    tags = get_link_tags(lid)
    tag_names = [t["name"] for t in tags]

    # Comments
    notes_resp = supabase.table("notes").select(
        "author, text, created_at"
    ).eq("link_id", lid).order("created_at", desc=True).limit(comments).execute()
    comment_list = []
    for n in (notes_resp.data or []):
        comment_list.append({
            "author": n.get("author", "anon"),
            "text": n.get("text", ""),
            "time": n.get("created_at", ""),
        })

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
    }


@router.get("/api/link")
async def api_link_lookup(url: str):
    """Look up a link by URL."""
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
async def api_link_note_create(link_id: int, body: NoteCreate):
    resp = supabase.table("notes").insert({
        "link_id": link_id, "author": body.author, "text": body.text
    }).execute()
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
        query = query.ilike("title", f"%{q}%")

    if sort == "score":
        query = query.order("direct_score", desc=True)
    else:
        query = query.order("created_at", desc=True)

    query = query.range(offset, offset + limit - 1)
    resp = query.execute()

    links = resp.data or []
    for link in links:
        link["tags"] = get_link_tags(link["id"])
        nc = supabase.table("notes").select("id", count="exact").eq("link_id", link["id"]).execute()
        link["note_count"] = nc.count or 0

    return {"links": links, "total": resp.count or 0}
