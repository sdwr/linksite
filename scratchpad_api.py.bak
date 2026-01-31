"""
Scratchpad API â€” link saving, notes, tags, related links, browse.
Import and mount on the FastAPI app from main.py.
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from urllib.parse import urlparse
import urllib.parse
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

def get_thum_url(url: str) -> str:
    """Get a screenshot via thum.io (free, no API key)."""
    return f"https://image.thum.io/get/width/600/{url}"

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
                meta_type = "youtube"
            elif "bsky.app" in domain or "bsky.social" in domain:
                # Skip bluesky for now - needs different handling
                meta_type = "bluesky"
            elif "reddit.com" in domain:
                meta_type = "reddit"
                result = extractor.extract_website_content(url)
            else:
                result = extractor.extract_website_content(url)
                meta_type = "website"
            
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
            
            # If no og_image, set thum.io screenshot as fallback
            cur = supabase.table("links").select("og_image_url, screenshot_url").eq("id", link_id).execute()
            if cur.data and not cur.data[0].get("og_image_url") and not cur.data[0].get("screenshot_url"):
                supabase.table("links").update({"screenshot_url": get_thum_url(url)}).eq("id", link_id).execute()
                print(f"[Scratchpad] Set thum.io screenshot for link {link_id}")
            
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
    """Find related links via vector similarity."""
    # Get the link's vector
    resp = supabase.table("links").select("content_vector").eq("id", link_id).execute()
    if not resp.data or not resp.data[0].get("content_vector"):
        return []
    
    # Can't do vector similarity via PostgREST easily without an RPC
    # Fallback: return links from same parent or same tags
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
    
    # Note count for list views
    link["note_count"] = len(link["notes"])
    
    return link


# --- API Routes ---

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
    # Check if exists
    existing = supabase.table("links").select("id").eq("url", body.url).execute()
    if existing.data:
        link_id = existing.data[0]["id"]
        # Still add note/tags if provided
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
    
    # Create new
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
    
    # Add note if provided
    if body.note:
        supabase.table("notes").insert({
            "link_id": link_id, "author": body.author, "text": body.note
        }).execute()
    
    # Add tags if provided
    if body.tags:
        _add_tags(link_id, body.tags, body.author)
    
    # Trigger async ingestion
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


def _add_tags(link_id: int, tag_names: list, author: str = "anonymous"):
    """Add tags to a link, creating tag entries if needed."""
    for name in tag_names:
        slug = name.lower().strip().replace(" ", "-")
        if not slug:
            continue
        
        # Find or create tag
        tag_resp = supabase.table("tags").select("id").eq("slug", slug).execute()
        if tag_resp.data:
            tag_id = tag_resp.data[0]["id"]
        else:
            new_tag = supabase.table("tags").insert({"name": name.strip(), "slug": slug}).execute()
            tag_id = new_tag.data[0]["id"]
        
        # Add link_tag (ignore if exists)
        try:
            supabase.table("link_tags").insert({
                "link_id": link_id, "tag_id": tag_id, "added_by": author
            }).execute()
        except Exception:
            pass  # Already exists


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
    
    # Filter out auto-parent stubs from browse unless specifically looking
    query = query.neq("source", "auto-parent")
    
    # Tag filter
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
    
    # Search
    if q:
        query = query.ilike("title", f"%{q}%")
    
    # Sort
    if sort == "score":
        query = query.order("direct_score", desc=True)
    elif sort == "noted":
        # Can't sort by note count via PostgREST easily, use recent as fallback
        query = query.order("created_at", desc=True)
    else:  # recent
        query = query.order("created_at", desc=True)
    
    query = query.range(offset, offset + limit - 1)
    resp = query.execute()
    
    links = resp.data or []
    
    if links:
        link_ids = [l["id"] for l in links]
        
        # Batch fetch all link_tags for these links
        lt_resp = supabase.table("link_tags").select("link_id, tag_id").in_("link_id", link_ids).execute()
        tag_ids = list(set(r["tag_id"] for r in (lt_resp.data or [])))
        tags_by_id = {}
        if tag_ids:
            tags_resp = supabase.table("tags").select("id, name, slug").in_("id", tag_ids).execute()
            tags_by_id = {t["id"]: t for t in (tags_resp.data or [])}
        
        # Group tags by link
        link_tag_map = {}
        for r in (lt_resp.data or []):
            link_tag_map.setdefault(r["link_id"], []).append(tags_by_id.get(r["tag_id"], {}))
        
        # Batch fetch note counts
        notes_resp = supabase.table("notes").select("link_id").in_("link_id", link_ids).execute()
        note_counts = {}
        for n in (notes_resp.data or []):
            note_counts[n["link_id"]] = note_counts.get(n["link_id"], 0) + 1
        
        for link in links:
            link["tags"] = link_tag_map.get(link["id"], [])
            link["note_count"] = note_counts.get(link["id"], 0)
    
    return {"links": links, "total": resp.count or 0}


# --- HTML Pages ---

DARK_STYLE = """
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e5e5e5; }
    a { color: #a78bfa; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .container { max-width: 900px; margin: 0 auto; padding: 24px; }
    .card { background: #171717; border: 1px solid #262626; border-radius: 12px; padding: 24px; margin-bottom: 16px; }
    .btn { display: inline-block; padding: 8px 16px; border-radius: 8px; border: 1px solid #404040; background: #262626; color: #e5e5e5; cursor: pointer; font-size: 14px; }
    .btn:hover { background: #333; border-color: #555; }
    .btn-primary { background: #7c3aed; border-color: #7c3aed; color: white; }
    .btn-primary:hover { background: #6d28d9; }
    input, textarea { background: #171717; border: 1px solid #333; border-radius: 8px; padding: 10px 14px; color: #e5e5e5; width: 100%; font-size: 14px; font-family: inherit; }
    input:focus, textarea:focus { outline: none; border-color: #7c3aed; }
    textarea { resize: vertical; min-height: 80px; }
    .tag { display: inline-block; padding: 3px 10px; border-radius: 20px; background: #1e1b4b; color: #a78bfa; font-size: 12px; margin: 2px; }
    .meta { color: #737373; font-size: 13px; }
    h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; }
    h2 { font-size: 20px; font-weight: 600; margin-bottom: 12px; color: #d4d4d4; }
    .note { padding: 12px 16px; border-left: 3px solid #7c3aed; background: #1a1a2e; border-radius: 0 8px 8px 0; margin-bottom: 8px; }
    .note-author { font-weight: 600; color: #a78bfa; }
    .note-time { color: #525252; font-size: 12px; }
    .preview-img { width: 100%; max-height: 400px; object-fit: cover; border-radius: 8px; margin-bottom: 16px; }
    .related-item { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid #1f1f1f; }
    .domain { color: #737373; font-size: 12px; }
    .nav { display: flex; gap: 16px; padding: 16px 0; border-bottom: 1px solid #262626; margin-bottom: 24px; }
    .form-group { margin-bottom: 16px; }
    .form-group label { display: block; margin-bottom: 6px; font-size: 13px; color: #a3a3a3; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
    .link-card { background: #171717; border: 1px solid #262626; border-radius: 12px; overflow: hidden; transition: border-color 0.2s; }
    .link-card:hover { border-color: #404040; }
    .link-card img { width: 100%; height: 160px; object-fit: cover; }
    .link-card .card-body { padding: 16px; }
    .link-card .card-title { font-weight: 600; font-size: 15px; line-height: 1.3; margin-bottom: 4px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .link-card .card-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
    .sort-bar { display: flex; gap: 8px; margin-bottom: 20px; align-items: center; }
    .sort-bar a { padding: 6px 12px; border-radius: 6px; font-size: 13px; color: #a3a3a3; }
    .sort-bar a.active { background: #262626; color: #e5e5e5; }
    .badge { background: #262626; color: #a3a3a3; font-size: 11px; padding: 2px 8px; border-radius: 10px; }
    .placeholder-img { width: 100%; height: 160px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); display: flex; align-items: center; justify-content: center; color: #525252; font-size: 24px; }
</style>
"""

NAV_HTML = """
<nav class="nav">
    <a href="/browse">Browse</a>
    <a href="/add">Check Link</a>
    <a href="/links">All Links</a>
    <a href="/admin">Admin</a>
</nav>
"""

def time_ago(dt_str):
    """Format a datetime string as 'X ago'."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        secs = diff.total_seconds()
        if secs < 60: return "just now"
        if secs < 3600: return f"{int(secs/60)}m ago"
        if secs < 86400: return f"{int(secs/3600)}h ago"
        return f"{int(secs/86400)}d ago"
    except:
        return ""


@router.get("/add", response_class=HTMLResponse)
async def page_add_link():
    """Minimal check/save link page."""
    return f"""<!DOCTYPE html><html><head><title>Check Link</title>{DARK_STYLE}
    <style>
        .check-container {{ display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 60vh; }}
        .check-form {{ width: 100%%; max-width: 600px; }}
        .check-form input {{ font-size: 18px; padding: 14px 20px; text-align: center; }}
        .check-form button {{ width: 100%%; margin-top: 12px; padding: 12px; font-size: 16px; }}
    </style></head><body>
    <div class="container">
        {NAV_HTML}
        <div class="check-container">
            <h1 style="margin-bottom:24px">Check Link</h1>
            <div class="check-form">
                <form method="POST" action="/add">
                    <input name="url" type="url" required placeholder="Paste a URL..." autofocus>
                    <input name="author" type="hidden" value="web-user">
                    <button type="submit" class="btn btn-primary">Check</button>
                </form>
            </div>
        </div>
    </div></body></html>"""


@router.post("/add")
async def page_add_link_submit(request: Request):
    """Check/save a link and redirect to its detail page."""
    form = await request.form()
    url = form.get("url", "").strip()
    if not url:
        return RedirectResponse("/add", status_code=303)
    
    author = form.get("author", "").strip() or "web-user"
    body = LinkCreate(url=url, author=author)
    result = await api_link_create(body)
    link_id = result["link"]["id"]
    
    return RedirectResponse(f"/link/{link_id}", status_code=303)


@router.get("/link/{link_id}", response_class=HTMLResponse)
async def page_link_detail(link_id: int):
    """Link detail page."""
    resp = supabase.table("links").select(
        "id, url, title, description, og_image_url, screenshot_url, source, submitted_by, parent_link_id, direct_score, created_at, feed_id, meta_json"
    ).eq("id", link_id).execute()
    
    if not resp.data:
        raise HTTPException(status_code=404, detail="Link not found")
    
    link = enrich_link(resp.data[0])
    parsed = urlparse(link["url"])
    domain = parsed.netloc
    
    # Image
    img_url = link.get("og_image_url") or link.get("screenshot_url") or get_thum_url(link["url"])
    img_html = f'<img src="{img_url}" class="preview-img" alt="" loading="lazy">'
    
    # Tags
    tags_html = " ".join(f'<span class="tag">{t["name"]}</span>' for t in link["tags"])
    if not tags_html:
        tags_html = '<span class="meta">No tags yet</span>'
    
    # Notes
    notes_html = ""
    for n in link["notes"]:
        notes_html += f'''<div class="note">
            <span class="note-author">{n["author"]}</span>
            <span class="note-time">{time_ago(n["created_at"])}</span>
            <div style="margin-top:6px">{n["text"]}</div>
        </div>'''
    if not notes_html:
        notes_html = '<p class="meta">No notes yet. Be the first!</p>'
    
    # Related
    related_html = ""
    for r in link["related"]:
        rd = urlparse(r["url"]).netloc
        related_html += f'''<div class="related-item">
            <a href="/link/{r["id"]}">{r.get("title") or r["url"][:60]}</a>
            <span class="domain">{rd}</span>
        </div>'''
    if not related_html:
        related_html = '<p class="meta">No related links found.</p>'
    
    # Parent
    parent_html = ""
    if link["parent"]:
        parent_html = f'<div style="margin-bottom:12px"><span class="meta">Part of:</span> <a href="/link/{link["parent"]["id"]}">{link["parent"].get("title") or link["parent"]["url"]}</a></div>'
    
    return f"""<!DOCTYPE html><html><head><title>{link.get("title") or "Link"} â€” Scratchpad</title>{DARK_STYLE}</head><body>
    <div class="container">
        {NAV_HTML}
        
        <div class="card">
            {img_html}
            <div class="meta" style="margin-bottom:8px">
                <span class="domain">{domain}</span>
                &middot; <a href="{link["url"]}" target="_blank">Visit â†—</a>
                &middot; {time_ago(link["created_at"])}
                {f' &middot; by {link["submitted_by"]}' if link.get("submitted_by") else ''}
            </div>
            {parent_html}
            <h1>{link.get("title") or link["url"]}</h1>
            <p style="margin-top:8px;color:#a3a3a3">{link.get("description") or ""}</p>
            
            <div style="margin-top:16px">{tags_html}</div>
            
            <!-- Add tag form -->
            <form method="POST" action="/link/{link_id}/add-tag" style="margin-top:12px;display:flex;gap:8px">
                <input name="tags" placeholder="Add tags (comma-separated)" style="flex:1">
                <input name="author" type="hidden" value="web-user">
                <button class="btn" type="submit">+ Tag</button>
            </form>
        </div>
        
        <div class="card">
            <h2>Notes ({len(link["notes"])})</h2>
            {notes_html}
            
            <form method="POST" action="/link/{link_id}/add-note" style="margin-top:16px">
                <div class="form-group">
                    <input name="author" placeholder="Your name" value="anonymous" style="margin-bottom:8px">
                    <textarea name="text" placeholder="Add a note..." required></textarea>
                </div>
                <button class="btn btn-primary" type="submit">Post Note</button>
            </form>
        </div>
        
        <div class="card">
            <h2>Related Links</h2>
            {related_html}
        </div>
    </div></body></html>"""


@router.post("/link/{link_id}/add-note")
async def page_add_note(link_id: int, request: Request):
    form = await request.form()
    author = form.get("author", "anonymous").strip() or "anonymous"
    text = form.get("text", "").strip()
    if text:
        supabase.table("notes").insert({"link_id": link_id, "author": author, "text": text}).execute()
    return RedirectResponse(f"/link/{link_id}", status_code=303)


@router.post("/link/{link_id}/add-tag")
async def page_add_tag(link_id: int, request: Request):
    form = await request.form()
    tags_str = form.get("tags", "").strip()
    author = form.get("author", "web-user").strip()
    if tags_str:
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        _add_tags(link_id, tags, author)
    return RedirectResponse(f"/link/{link_id}", status_code=303)


@router.get("/browse", response_class=HTMLResponse)
async def page_browse(
    tag: Optional[str] = None,
    sort: str = "recent",
    q: Optional[str] = None
):
    """Browse all links â€” grid of cards."""
    result = await api_links_browse(tag=tag, sort=sort, q=q, limit=50, offset=0)
    links = result["links"]
    total = result["total"]
    
    # All tags for filter
    all_tags = supabase.table("tags").select("name, slug").order("name").execute()
    tag_filter_html = ""
    for t in (all_tags.data or []):
        active = "active" if tag == t["slug"] else ""
        tag_filter_html += f'<a href="/browse?tag={t["slug"]}&sort={sort}" class="sort-bar a {active}" style="background:{("#1e1b4b" if active else "transparent")}">{t["name"]}</a>'
    
    # Cards
    cards_html = ""
    for link in links:
        img_url = link.get("og_image_url") or link.get("screenshot_url") or get_thum_url(link["url"])
        img_html = f'<img src="{img_url}" alt="">' if img_url else '<div class="placeholder-img">ðŸ”—</div>'
        domain = urlparse(link["url"]).netloc
        tags_html = " ".join(f'<span class="tag">{t["name"]}</span>' for t in link.get("tags", []))
        note_badge = f'<span class="badge">{link["note_count"]} notes</span>' if link.get("note_count") else ""
        
        cards_html += f'''<a href="/link/{link["id"]}" class="link-card" style="text-decoration:none;color:inherit">
            {img_html}
            <div class="card-body">
                <div class="card-title">{link.get("title") or link["url"][:50]}</div>
                <div class="domain">{domain}</div>
                <div style="margin-top:6px">{tags_html}</div>
                <div class="card-meta">
                    <span class="meta">{time_ago(link["created_at"])}</span>
                    {note_badge}
                </div>
            </div>
        </a>'''
    
    if not cards_html:
        cards_html = '<p class="meta">No links found. <a href="/add">Add one!</a></p>'
    
    return f"""<!DOCTYPE html><html><head><title>Scratchpad â€” Links</title>{DARK_STYLE}</head><body>
    <div class="container">
        {NAV_HTML}
        <h1>Links</h1>
        <div class="sort-bar" style="margin-top:16px">
            <a href="/browse?sort=recent{'&tag='+tag if tag else ''}" class="{'active' if sort=='recent' else ''}">Recent</a>
            <a href="/browse?sort=score{'&tag='+tag if tag else ''}" class="{'active' if sort=='score' else ''}">Top</a>
            {f'| {tag_filter_html}' if tag_filter_html else ''}
            <div style="flex:1"></div>
            <form style="display:flex;gap:8px" action="/browse">
                <input name="q" placeholder="Search..." value="{q or ''}" style="width:200px">
                <input name="sort" type="hidden" value="{sort}">
                <button class="btn" type="submit">Search</button>
            </form>
        </div>
        <div class="grid">{cards_html}</div>
        <p class="meta" style="margin-top:20px">{total} links total</p>
    </div></body></html>"""
