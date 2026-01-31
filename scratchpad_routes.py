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
    
    # Add tag and note count to each
    for link in links:
        link["tags"] = get_link_tags(link["id"])
        nc = supabase.table("notes").select("id", count="exact").eq("link_id", link["id"]).execute()
        link["note_count"] = nc.count or 0
    
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
    <a href="/scratchpad">Browse</a>
    <a href="/scratchpad/add">+ Add Link</a>
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


@router.get("/scratchpad/add", response_class=HTMLResponse)
async def page_add_link():
    """Form to add a new link."""
    return f"""<!DOCTYPE html><html><head><title>Add Link</title>{DARK_STYLE}</head><body>
    <div class="container">
        {NAV_HTML}
        <h1>Save a Link</h1>
        <div class="card" style="margin-top:16px">
            <form method="POST" action="/scratchpad/add">
                <div class="form-group">
                    <label>URL *</label>
                    <input name="url" type="url" required placeholder="https://example.com/article">
                </div>
                <div class="form-group">
                    <label>Title (auto-scraped if blank)</label>
                    <input name="title" placeholder="Optional title">
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <textarea name="description" placeholder="Optional description"></textarea>
                </div>
                <div class="form-group">
                    <label>Tags (comma-separated)</label>
                    <input name="tags" placeholder="ai, research, interesting">
                </div>
                <div class="form-group">
                    <label>Note</label>
                    <textarea name="note" placeholder="Why is this interesting? Any observations?"></textarea>
                </div>
                <div class="form-group">
                    <label>Your Name</label>
                    <input name="author" placeholder="anonymous" value="anonymous">
                </div>
                <button type="submit" class="btn btn-primary">Save Link</button>
            </form>
        </div>
    </div></body></html>"""


@router.post("/scratchpad/add")
async def page_add_link_submit(request: Request):
    """Handle form submission."""
    form = await request.form()
    url = form.get("url", "").strip()
    if not url:
        return RedirectResponse("/scratchpad/add", status_code=303)
    
    title = form.get("title", "").strip() or None
    description = form.get("description", "").strip() or None
    tags_str = form.get("tags", "").strip()
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None
    note = form.get("note", "").strip() or None
    author = form.get("author", "").strip() or "anonymous"
    
    body = LinkCreate(url=url, title=title, description=description, tags=tags, note=note, author=author)
    result = await api_link_create(body)
    link_id = result["link"]["id"]
    
    return RedirectResponse(f"/scratchpad/link/{link_id}", status_code=303)


@router.get("/scratchpad/link/{link_id}", response_class=HTMLResponse)
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
    img_url = link.get("og_image_url") or link.get("screenshot_url")
    img_html = f'<img src="{img_url}" class="preview-img" alt="">' if img_url else '<div class="placeholder-img">No preview</div>'
    
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
            <a href="/scratchpad/link/{r["id"]}">{r.get("title") or r["url"][:60]}</a>
            <span class="domain">{rd}</span>
        </div>'''
    if not related_html:
        related_html = '<p class="meta">No related links found.</p>'
    
    # Parent
    parent_html = ""
    if link["parent"]:
        parent_html = f'<div style="margin-bottom:12px"><span class="meta">Part of:</span> <a href="/scratchpad/link/{link["parent"]["id"]}">{link["parent"].get("title") or link["parent"]["url"]}</a></div>'
    
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
            <form method="POST" action="/scratchpad/link/{link_id}/add-tag" style="margin-top:12px;display:flex;gap:8px">
                <input name="tags" placeholder="Add tags (comma-separated)" style="flex:1">
                <input name="author" type="hidden" value="web-user">
                <button class="btn" type="submit">+ Tag</button>
            </form>
        </div>
        
        <div class="card">
            <h2>Notes ({len(link["notes"])})</h2>
            {notes_html}
            
            <form method="POST" action="/scratchpad/link/{link_id}/add-note" style="margin-top:16px">
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


@router.post("/scratchpad/link/{link_id}/add-note")
async def page_add_note(link_id: int, request: Request):
    form = await request.form()
    author = form.get("author", "anonymous").strip() or "anonymous"
    text = form.get("text", "").strip()
    if text:
        supabase.table("notes").insert({"link_id": link_id, "author": author, "text": text}).execute()
    return RedirectResponse(f"/scratchpad/link/{link_id}", status_code=303)


@router.post("/scratchpad/link/{link_id}/add-tag")
async def page_add_tag(link_id: int, request: Request):
    form = await request.form()
    tags_str = form.get("tags", "").strip()
    author = form.get("author", "web-user").strip()
    if tags_str:
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        _add_tags(link_id, tags, author)
    return RedirectResponse(f"/scratchpad/link/{link_id}", status_code=303)


@router.get("/scratchpad", response_class=HTMLResponse)
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
        tag_filter_html += f'<a href="/scratchpad?tag={t["slug"]}&sort={sort}" class="sort-bar a {active}" style="background:{("#1e1b4b" if active else "transparent")}">{t["name"]}</a>'
    
    # Cards
    cards_html = ""
    for link in links:
        img_url = link.get("og_image_url") or link.get("screenshot_url")
        img_html = f'<img src="{img_url}" alt="">' if img_url else '<div class="placeholder-img">ðŸ”—</div>'
        domain = urlparse(link["url"]).netloc
        tags_html = " ".join(f'<span class="tag">{t["name"]}</span>' for t in link.get("tags", []))
        note_badge = f'<span class="badge">{link["note_count"]} notes</span>' if link.get("note_count") else ""
        
        cards_html += f'''<a href="/scratchpad/link/{link["id"]}" class="link-card" style="text-decoration:none;color:inherit">
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
        cards_html = '<p class="meta">No links found. <a href="/scratchpad/add">Add one!</a></p>'
    
    return f"""<!DOCTYPE html><html><head><title>Scratchpad â€” Links</title>{DARK_STYLE}</head><body>
    <div class="container">
        {NAV_HTML}
        <h1>Links</h1>
        <div class="sort-bar" style="margin-top:16px">
            <a href="/scratchpad?sort=recent{'&tag='+tag if tag else ''}" class="{'active' if sort=='recent' else ''}">Recent</a>
            <a href="/scratchpad?sort=score{'&tag='+tag if tag else ''}" class="{'active' if sort=='score' else ''}">Top</a>
            {f'| {tag_filter_html}' if tag_filter_html else ''}
            <div style="flex:1"></div>
            <form style="display:flex;gap:8px" action="/scratchpad">
                <input name="q" placeholder="Search..." value="{q or ''}" style="width:200px">
                <input name="sort" type="hidden" value="{sort}">
                <button class="btn" type="submit">Search</button>
            </form>
        </div>
        <div class="grid">{cards_html}</div>
        <p class="meta" style="margin-top:20px">{total} links total</p>
    </div></body></html>"""
"""
Scratchpad API endpoints and HTML pages for linksite.
This file gets imported by main.py
"""

import re
from typing import Optional, List
from urllib.parse import urlparse
from fastapi import BackgroundTasks, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel


class LinkCreate(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list] = None
    note: Optional[str] = None
    author: Optional[str] = None

class LinkPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

class NoteCreate(BaseModel):
    author: Optional[str] = "anonymous"
    text: str

class TagsAdd(BaseModel):
    tags: list
    author: Optional[str] = "anonymous"


def get_base_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split('/')[0]
    except Exception:
        return ""


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


def enrich_link_data(supabase, link: dict) -> dict:
    link_id = link['id']
    notes_resp = supabase.table('notes').select('*').eq('link_id', link_id).order('created_at', desc=True).execute()
    link['notes'] = notes_resp.data or []
    lt_resp = supabase.table('link_tags').select('tag_id').eq('link_id', link_id).execute()
    tag_ids = [lt['tag_id'] for lt in (lt_resp.data or [])]
    tags = []
    if tag_ids:
        tags_resp = supabase.table('tags').select('*').in_('id', tag_ids).execute()
        tags = tags_resp.data or []
    link['tags'] = tags
    link.pop('content_vector', None)
    link.pop('comment_vector', None)
    return link


def find_related_links(supabase, link_id: int, limit: int = 10) -> list:
    try:
        link_resp = supabase.table('links').select('content_vector').eq('id', link_id).execute()
        if not link_resp.data or not link_resp.data[0].get('content_vector'):
            resp = supabase.table('links').select('id, url, title, og_image_url, created_at').neq('id', link_id).order('created_at', desc=True).limit(limit).execute()
            return resp.data or []
        vec = link_resp.data[0]['content_vector']
        try:
            result = supabase.rpc('match_links', {
                'query_embedding': vec,
                'match_threshold': 0.3,
                'match_count': limit + 1
            }).execute()
            related = [r for r in (result.data or []) if r['id'] != link_id][:limit]
            return related
        except Exception:
            resp = supabase.table('links').select('id, url, title, og_image_url, created_at').neq('id', link_id).order('created_at', desc=True).limit(limit).execute()
            return resp.data or []
    except Exception as e:
        print(f"Error finding related links: {e}")
        return []


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


DARK_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #0f172a; color: #e2e8f0; line-height: 1.6; }
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; color: #93bbfc; }
.topbar { background: #1e293b; border-bottom: 1px solid #334155; padding: 12px 24px; display: flex; gap: 24px; align-items: center; }
.topbar .brand { color: #38bdf8; font-size: 18px; font-weight: 700; margin-right: auto; }
.topbar a { color: #94a3b8; font-weight: 500; font-size: 14px; }
.topbar a:hover { color: #e2e8f0; text-decoration: none; }
.container { max-width: 900px; margin: 24px auto; padding: 0 16px; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; margin-bottom: 20px; }
h1 { font-size: 24px; margin-bottom: 16px; color: #f1f5f9; }
h2 { font-size: 18px; margin-bottom: 12px; color: #e2e8f0; }
.pill { display: inline-block; background: #312e81; color: #a5b4fc; padding: 3px 10px; border-radius: 12px; font-size: 12px; margin: 2px 4px 2px 0; font-weight: 500; }
.pill-remove { color: #f87171; margin-left: 4px; cursor: pointer; font-weight: 700; text-decoration: none; }
.pill-remove:hover { color: #ef4444; }
.img-preview { max-width: 100%; max-height: 300px; border-radius: 8px; margin: 12px 0; object-fit: cover; }
.note { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; }
.note .meta { font-size: 12px; color: #64748b; margin-bottom: 4px; }
.note .text { font-size: 14px; color: #cbd5e1; white-space: pre-wrap; }
.related-link { display: block; padding: 8px 12px; border: 1px solid #334155; border-radius: 8px; margin-bottom: 6px; background: #0f172a; }
.related-link:hover { background: #1e293b; border-color: #475569; text-decoration: none; }
.related-link .r-title { color: #e2e8f0; font-weight: 500; }
.related-link .r-url { color: #64748b; font-size: 12px; }
input[type="text"], input[type="url"], textarea, select {
    width: 100%; padding: 10px 14px; background: #0f172a; border: 1px solid #334155;
    border-radius: 8px; color: #e2e8f0; font-size: 14px; margin-bottom: 10px; font-family: inherit; }
input:focus, textarea:focus { outline: none; border-color: #60a5fa; }
textarea { min-height: 80px; resize: vertical; }
.btn { display: inline-block; cursor: pointer; padding: 10px 20px; border-radius: 8px; border: none;
       font-size: 14px; font-weight: 600; text-align: center; }
.btn-primary { background: #2563eb; color: #fff; }
.btn-primary:hover { background: #1d4ed8; text-decoration: none; }
.btn-sm { padding: 6px 14px; font-size: 13px; }
.btn-ghost { background: transparent; border: 1px solid #475569; color: #94a3b8; }
.btn-ghost:hover { background: #1e293b; color: #e2e8f0; }
label { display: block; font-size: 13px; color: #94a3b8; margin-bottom: 4px; font-weight: 500; }
.msg-ok { background: #064e3b; color: #6ee7b7; padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; border: 1px solid #065f46; }
.msg-err { background: #450a0a; color: #fca5a5; padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; border: 1px solid #7f1d1d; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.link-card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; overflow: hidden; transition: border-color 0.2s; display: block; }
.link-card:hover { border-color: #475569; text-decoration: none; }
.link-card .thumb { width: 100%; height: 160px; object-fit: cover; background: #0f172a; display: block; }
.link-card .thumb-placeholder { width: 100%; height: 160px; background: linear-gradient(135deg, #1e293b, #0f172a); display: flex; align-items: center; justify-content: center; color: #334155; font-size: 40px; }
.link-card .body { padding: 14px; }
.link-card .card-title { color: #f1f5f9; font-weight: 600; font-size: 15px; line-height: 1.3; margin-bottom: 4px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.link-card .card-domain { color: #64748b; font-size: 12px; margin-bottom: 8px; }
.link-card .card-pills { margin-bottom: 6px; }
.link-card .card-meta { color: #475569; font-size: 12px; display: flex; justify-content: space-between; }
.sort-bar { display: flex; gap: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
.sort-bar a { padding: 6px 14px; border-radius: 20px; font-size: 13px; background: #1e293b; color: #94a3b8; border: 1px solid #334155; text-decoration: none; }
.sort-bar a:hover { color: #e2e8f0; border-color: #475569; }
.sort-bar a.active { background: #2563eb; color: #fff; border-color: #2563eb; }
.search-box form { display: flex; gap: 8px; width: 100%; margin-bottom: 16px; }
.search-box input { flex: 1; margin-bottom: 0; }
.inline-flex { display: flex; gap: 8px; align-items: center; }
"""


def dark_nav():
    return """<div class="topbar">
        <span class="brand">&#128279; Linksite</span>
        <a href="/browse">Browse</a>
        <a href="/add">+ Add Link</a>
        <a href="/links">Legacy</a>
        <a href="/admin">Admin</a>
    </div>"""


def dark_page(title, body):
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Linksite</title><style>{DARK_CSS}</style></head><body>
{dark_nav()}<div class="container">{body}</div></body></html>"""


def register_scratchpad_routes(app, supabase, vectorize_fn):
    """Register all scratchpad routes on the FastAPI app."""
    
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
            domain = get_base_domain(url)
            if not domain:
                return
            base_url = f"https://{domain}"
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            if not path and not parsed.query:
                return
            existing = supabase.table('links').select('id').eq('url', base_url).execute()
            if existing.data:
                parent_id = existing.data[0]['id']
            else:
                result = supabase.table('links').insert({
                    'url': base_url,
                    'title': domain,
                    'source': 'auto-parent',
                }).execute()
                parent_id = result.data[0]['id'] if result.data else None
            if parent_id and parent_id != link_id:
                supabase.table('links').update({'parent_link_id': parent_id}).eq('id', link_id).execute()
        except Exception as e:
            print(f"[Parent] Error for {url}: {e}")

    # --- API: GET /api/link?url= ---
    @app.get("/api/link")
    async def api_get_link(url: str):
        resp = supabase.table('links').select('*').eq('url', url).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Link not found")
        link = enrich_link_data(supabase, resp.data[0])
        link['related'] = find_related_links(supabase, link['id'], 5)
        return link

    # --- API: POST /api/link ---
    @app.post("/api/link")
    async def api_create_link(body: LinkCreate, background_tasks: BackgroundTasks):
        url = body.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")
        existing = supabase.table('links').select('*').eq('url', url).execute()
        if existing.data:
            link = enrich_link_data(supabase, existing.data[0])
            return {"link": link, "created": False}
        insert_data = {
            'url': url,
            'title': body.title or '',
            'description': body.description or '',
            'submitted_by': body.author or 'anonymous',
            'source': 'scratchpad',
        }
        result = supabase.table('links').insert(insert_data).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create link")
        link = result.data[0]
        link_id = link['id']
        if body.tags:
            for tag_name in body.tags:
                tag = get_or_create_tag(supabase, tag_name)
                if tag:
                    try:
                        supabase.table('link_tags').insert({
                            'link_id': link_id, 'tag_id': tag['id'],
                            'added_by': body.author or 'anonymous',
                        }).execute()
                    except Exception:
                        pass
        if body.note:
            supabase.table('notes').insert({
                'link_id': link_id, 'author': body.author or 'anonymous',
                'text': body.note,
            }).execute()
        background_tasks.add_task(_ingest_link_content, link_id, url)
        background_tasks.add_task(_ensure_parent_site, url, link_id)
        link = enrich_link_data(supabase, link)
        return {"link": link, "created": True}

    # --- API: PATCH /api/link/<id> ---
    @app.patch("/api/link/{link_id}")
    async def api_patch_link(link_id: int, body: LinkPatch):
        update = {}
        if body.title is not None:
            update['title'] = body.title
        if body.description is not None:
            update['description'] = body.description
        if not update:
            raise HTTPException(status_code=400, detail="Nothing to update")
        supabase.table('links').update(update).eq('id', link_id).execute()
        resp = supabase.table('links').select('*').eq('id', link_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Link not found")
        return enrich_link_data(supabase, resp.data[0])

    # --- API: GET /api/link/<id>/notes ---
    @app.get("/api/link/{link_id}/notes")
    async def api_get_notes(link_id: int):
        resp = supabase.table('notes').select('*').eq('link_id', link_id).order('created_at', desc=True).execute()
        return resp.data or []

    # --- API: POST /api/link/<id>/notes ---
    @app.post("/api/link/{link_id}/notes")
    async def api_create_note(link_id: int, body: NoteCreate):
        link_resp = supabase.table('links').select('id').eq('id', link_id).execute()
        if not link_resp.data:
            raise HTTPException(status_code=404, detail="Link not found")
        result = supabase.table('notes').insert({
            'link_id': link_id, 'author': body.author or 'anonymous', 'text': body.text,
        }).execute()
        return result.data[0] if result.data else {}

    # --- API: POST /api/link/<id>/tags ---
    @app.post("/api/link/{link_id}/tags")
    async def api_add_tags(link_id: int, body: TagsAdd):
        link_resp = supabase.table('links').select('id').eq('id', link_id).execute()
        if not link_resp.data:
            raise HTTPException(status_code=404, detail="Link not found")
        added = []
        for tag_name in body.tags:
            tag = get_or_create_tag(supabase, tag_name)
            if tag:
                try:
                    supabase.table('link_tags').insert({
                        'link_id': link_id, 'tag_id': tag['id'],
                        'added_by': body.author or 'anonymous',
                    }).execute()
                    added.append(tag)
                except Exception:
                    pass
        return {"added": added}

    # --- API: DELETE /api/link/<id>/tags/<slug> ---
    @app.delete("/api/link/{link_id}/tags/{slug}")
    async def api_remove_tag(link_id: int, slug: str):
        tag_resp = supabase.table('tags').select('id').eq('slug', slug).execute()
        if not tag_resp.data:
            raise HTTPException(status_code=404, detail="Tag not found")
        tag_id = tag_resp.data[0]['id']
        supabase.table('link_tags').delete().eq('link_id', link_id).eq('tag_id', tag_id).execute()
        return {"ok": True}

    # --- API: GET /api/link/<id>/related ---
    @app.get("/api/link/{link_id}/related")
    async def api_related_links(link_id: int):
        return find_related_links(supabase, link_id, 10)

    # --- API: GET /api/links (browse/search) ---
    @app.get("/api/links")
    async def api_browse_links(
        tag: Optional[str] = None,
        sort: Optional[str] = "recent",
        q: Optional[str] = None,
        limit: int = 20
    ):
        limit = min(limit, 100)
        if tag:
            tag_resp = supabase.table('tags').select('id').eq('slug', tag).execute()
            if not tag_resp.data:
                return []
            tag_id = tag_resp.data[0]['id']
            lt_resp = supabase.table('link_tags').select('link_id').eq('tag_id', tag_id).execute()
            link_ids = [lt['link_id'] for lt in (lt_resp.data or [])]
            if not link_ids:
                return []
            query = supabase.table('links').select('id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by, parent_link_id').in_('id', link_ids)
        elif q:
            query = supabase.table('links').select('id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by, parent_link_id').or_(f'title.ilike.%{q}%,url.ilike.%{q}%,description.ilike.%{q}%')
        else:
            query = supabase.table('links').select('id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by, parent_link_id')
        if sort == "score":
            query = query.order('direct_score', desc=True)
        else:
            query = query.order('created_at', desc=True)
        query = query.limit(limit)
        resp = query.execute()
        links = resp.data or []
        for link in links:
            lid = link['id']
            notes_resp = supabase.table('notes').select('id').eq('link_id', lid).execute()
            link['note_count'] = len(notes_resp.data or [])
            lt_resp = supabase.table('link_tags').select('tag_id').eq('link_id', lid).execute()
            tids = [lt['tag_id'] for lt in (lt_resp.data or [])]
            if tids:
                tags_resp = supabase.table('tags').select('slug, name').in_('id', tids).execute()
                link['tags'] = tags_resp.data or []
            else:
                link['tags'] = []
        if sort == "noted":
            links.sort(key=lambda x: x.get('note_count', 0), reverse=True)
        return links

    # ========== HTML Pages ==========

    # --- GET /add ---
    @app.get("/add", response_class=HTMLResponse)
    async def page_add_link(message: Optional[str] = None, error: Optional[str] = None):
        msgs = ""
        if message:
            msgs += f'<div class="msg-ok">{_esc(message)}</div>'
        if error:
            msgs += f'<div class="msg-err">{_esc(error)}</div>'
        body = f"""{msgs}
        <h1>Add a Link</h1>
        <div class="card">
            <form method="POST" action="/add">
                <label>URL *</label>
                <input type="url" name="url" placeholder="https://..." required>
                <label>Title (optional -- will be auto-detected)</label>
                <input type="text" name="title" placeholder="Page title">
                <label>Description (optional)</label>
                <textarea name="description" placeholder="What is this link about?"></textarea>
                <label>Tags (comma-separated)</label>
                <input type="text" name="tags" placeholder="ai, research, cool">
                <label>Note (optional)</label>
                <textarea name="note" placeholder="Any notes about this link..."></textarea>
                <label>Your name</label>
                <input type="text" name="author" placeholder="anonymous">
                <br>
                <button type="submit" class="btn btn-primary">Save Link</button>
            </form>
        </div>"""
        return HTMLResponse(dark_page("Add Link", body))

    @app.post("/add", response_class=HTMLResponse)
    async def page_add_link_post(
        background_tasks: BackgroundTasks,
        url: str = Form(...),
        title: str = Form(""),
        description: str = Form(""),
        tags: str = Form(""),
        note: str = Form(""),
        author: str = Form(""),
    ):
        url = url.strip()
        if not url:
            return RedirectResponse(url="/add?error=URL+is+required", status_code=303)
        author = author.strip() or "anonymous"
        existing = supabase.table('links').select('id').eq('url', url).execute()
        if existing.data:
            link_id = existing.data[0]['id']
            return RedirectResponse(url=f"/link/{link_id}?message=Link+already+exists", status_code=303)
        insert_data = {
            'url': url,
            'title': title.strip() or '',
            'description': description.strip() or '',
            'submitted_by': author,
            'source': 'scratchpad',
        }
        result = supabase.table('links').insert(insert_data).execute()
        if not result.data:
            return RedirectResponse(url="/add?error=Failed+to+create+link", status_code=303)
        link_id = result.data[0]['id']
        if tags.strip():
            for tag_name in tags.split(','):
                tag_name = tag_name.strip()
                if tag_name:
                    tag = get_or_create_tag(supabase, tag_name)
                    if tag:
                        try:
                            supabase.table('link_tags').insert({
                                'link_id': link_id, 'tag_id': tag['id'], 'added_by': author,
                            }).execute()
                        except Exception:
                            pass
        if note.strip():
            supabase.table('notes').insert({
                'link_id': link_id, 'author': author, 'text': note.strip(),
            }).execute()
        background_tasks.add_task(_ingest_link_content, link_id, url)
        background_tasks.add_task(_ensure_parent_site, url, link_id)
        return RedirectResponse(url=f"/link/{link_id}?message=Link+saved!+Content+being+extracted...", status_code=303)

    # --- GET /link/<id> ---
    @app.get("/link/{link_id}", response_class=HTMLResponse)
    async def page_link_detail(link_id: int, message: Optional[str] = None, error: Optional[str] = None):
        resp = supabase.table('links').select('*').eq('id', link_id).execute()
        if not resp.data:
            return HTMLResponse(dark_page("Not Found", '<div class="msg-err">Link not found.</div>'))
        link = enrich_link_data(supabase, resp.data[0])
        related = find_related_links(supabase, link_id, 6)
        msgs = ""
        if message:
            msgs += f'<div class="msg-ok">{_esc(message)}</div>'
        if error:
            msgs += f'<div class="msg-err">{_esc(error)}</div>'
        title = _esc(link.get('title') or link.get('url', ''))
        url = link.get('url', '')
        domain = get_base_domain(url)
        description = _esc(link.get('description') or '')[:500]
        og_img = link.get('og_image_url') or link.get('screenshot_url') or ''
        img_html = f'<img src="{_esc(og_img)}" class="img-preview" alt="preview">' if og_img else ""
        tags_html = ""
        for t in link.get('tags', []):
            sl = _esc(t.get('slug', ''))
            nm = _esc(t.get('name', sl))
            tags_html += f'<span class="pill">{nm}<a href="/link/{link_id}/remove-tag/{sl}" class="pill-remove">&times;</a></span>'
        if not tags_html:
            tags_html = '<span style="color:#475569;font-size:13px">No tags yet</span>'
        parent_html = ""
        if link.get('parent_link_id'):
            pr = supabase.table('links').select('id, url, title').eq('id', link['parent_link_id']).execute()
            if pr.data:
                p = pr.data[0]
                parent_html = f'<div style="margin-bottom:12px"><span style="color:#64748b;font-size:13px">Parent site:</span> <a href="/link/{p["id"]}">{_esc(p.get("title") or p.get("url"))}</a></div>'
        notes_html = ""
        for n in link.get('notes', []):
            na = _esc(n.get('author', 'anonymous'))
            nt = _esc(n.get('text', ''))
            nc = n.get('created_at', '')[:16].replace('T', ' ')
            notes_html += f'<div class="note"><div class="meta"><strong>{na}</strong> &middot; {nc}</div><div class="text">{nt}</div></div>'
        if not notes_html:
            notes_html = '<p style="color:#475569;font-size:13px">No notes yet.</p>'
        related_html = ""
        for r in related:
            rt = _esc(r.get('title') or r.get('url', ''))
            rd = get_base_domain(r.get('url', ''))
            rid = r.get('id')
            related_html += f'<a href="/link/{rid}" class="related-link"><span class="r-title">{rt}</span><br><span class="r-url">{_esc(rd)}</span></a>'
        if not related_html:
            related_html = '<p style="color:#475569;font-size:13px">No related links found.</p>'
        body = f"""{msgs}
        <div class="card">
            <h1>{title}</h1>
            <div style="color:#64748b;font-size:13px;margin-bottom:8px"><a href="{_esc(url)}" target="_blank">{_esc(domain)}</a> &middot; <a href="{_esc(url)}" target="_blank">Open &nearr;</a></div>
            {parent_html}{img_html}
            <p style="margin:12px 0;color:#94a3b8">{description}</p>
            <div style="margin:12px 0">{tags_html}</div>
            <div style="font-size:12px;color:#475569;margin-top:8px">Added by {_esc(link.get('submitted_by') or 'unknown')} &middot; {(link.get('created_at') or '')[:16].replace('T', ' ')}</div>
        </div>
        <div class="card">
            <h2>Notes ({len(link.get('notes', []))})</h2>
            {notes_html}
            <form method="POST" action="/link/{link_id}/add-note" style="margin-top:12px">
                <div class="inline-flex" style="margin-bottom:8px"><input type="text" name="author" placeholder="Your name" style="width:200px;margin-bottom:0"></div>
                <textarea name="text" placeholder="Add a note..." required></textarea>
                <button type="submit" class="btn btn-primary btn-sm">Add Note</button>
            </form>
        </div>
        <div class="card">
            <h2>Add Tags</h2>
            <form method="POST" action="/link/{link_id}/add-tags" class="inline-flex">
                <input type="text" name="tags" placeholder="tag1, tag2, ..." style="flex:1;margin-bottom:0" required>
                <input type="text" name="author" placeholder="Your name" style="width:150px;margin-bottom:0">
                <button type="submit" class="btn btn-primary btn-sm">Add</button>
            </form>
        </div>
        <div class="card">
            <h2>Related Links</h2>
            {related_html}
        </div>"""
        return HTMLResponse(dark_page(title, body))

    # --- HTML form handlers ---
    @app.post("/link/{link_id}/add-note")
    async def page_add_note(link_id: int, text: str = Form(...), author: str = Form("")):
        author = author.strip() or "anonymous"
        supabase.table('notes').insert({'link_id': link_id, 'author': author, 'text': text.strip()}).execute()
        return RedirectResponse(url=f"/link/{link_id}?message=Note+added", status_code=303)

    @app.post("/link/{link_id}/add-tags")
    async def page_add_tags(link_id: int, tags: str = Form(...), author: str = Form("")):
        author = author.strip() or "anonymous"
        for tag_name in tags.split(','):
            tag_name = tag_name.strip()
            if tag_name:
                tag = get_or_create_tag(supabase, tag_name)
                if tag:
                    try:
                        supabase.table('link_tags').insert({'link_id': link_id, 'tag_id': tag['id'], 'added_by': author}).execute()
                    except Exception:
                        pass
        return RedirectResponse(url=f"/link/{link_id}?message=Tags+added", status_code=303)

    @app.get("/link/{link_id}/remove-tag/{slug}")
    async def page_remove_tag(link_id: int, slug: str):
        tag_resp = supabase.table('tags').select('id').eq('slug', slug).execute()
        if tag_resp.data:
            supabase.table('link_tags').delete().eq('link_id', link_id).eq('tag_id', tag_resp.data[0]['id']).execute()
        return RedirectResponse(url=f"/link/{link_id}?message=Tag+removed", status_code=303)

    # ========== Browse Page ==========
    @app.get("/browse", response_class=HTMLResponse)
    async def page_browse(tag: Optional[str] = None, sort: Optional[str] = "recent", q: Optional[str] = None):
        try:
            all_tags_resp = supabase.table('tags').select('slug, name').order('name').execute()
            all_tags = all_tags_resp.data or []
            links = []
            if tag:
                tag_resp = supabase.table('tags').select('id').eq('slug', tag).execute()
                if tag_resp.data:
                    tag_id = tag_resp.data[0]['id']
                    lt_resp = supabase.table('link_tags').select('link_id').eq('tag_id', tag_id).execute()
                    link_ids = [lt['link_id'] for lt in (lt_resp.data or [])]
                    if link_ids:
                        qr = supabase.table('links').select('id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by').in_('id', link_ids)
                        if sort == "score":
                            qr = qr.order('direct_score', desc=True)
                        else:
                            qr = qr.order('created_at', desc=True)
                        links = (qr.limit(60).execute()).data or []
            elif q:
                qr = supabase.table('links').select('id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by').or_(f'title.ilike.%{q}%,url.ilike.%{q}%,description.ilike.%{q}%')
                if sort == "score":
                    qr = qr.order('direct_score', desc=True)
                else:
                    qr = qr.order('created_at', desc=True)
                links = (qr.limit(60).execute()).data or []
            else:
                qr = supabase.table('links').select('id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by')
                if sort == "score":
                    qr = qr.order('direct_score', desc=True)
                else:
                    qr = qr.order('created_at', desc=True)
                links = (qr.limit(60).execute()).data or []
            for link in links:
                lid = link['id']
                nr = supabase.table('notes').select('id').eq('link_id', lid).execute()
                link['note_count'] = len(nr.data or [])
                lt = supabase.table('link_tags').select('tag_id').eq('link_id', lid).execute()
                tids = [x['tag_id'] for x in (lt.data or [])]
                if tids:
                    tr = supabase.table('tags').select('slug, name').in_('id', tids).execute()
                    link['tags'] = tr.data or []
                else:
                    link['tags'] = []
            if sort == "noted":
                links.sort(key=lambda x: x.get('note_count', 0), reverse=True)

            def sl(s, label):
                act = ' active' if sort == s else ''
                params = f'sort={s}'
                if tag:
                    params += f'&tag={_esc(tag)}'
                if q:
                    params += f'&q={_esc(q)}'
                return f'<a href="/browse?{params}" class="{act}">{label}</a>'
            sort_html = f'<div class="sort-bar"><span style="color:#64748b;font-size:13px">Sort:</span>{sl("recent","&#128337; Recent")}{sl("score","&#11088; Top")}{sl("noted","&#128221; Most Noted")}</div>'
            tag_html = '<div class="sort-bar"><span style="color:#64748b;font-size:13px">Tags:</span>'
            act_all = ' active' if not tag else ''
            tag_html += f'<a href="/browse?sort={sort}" class="{act_all}">All</a>'
            for t in all_tags:
                ac = ' active' if tag == t['slug'] else ''
                tag_html += f'<a href="/browse?tag={_esc(t["slug"])}&sort={sort}" class="{ac}">{_esc(t["name"])}</a>'
            tag_html += '</div>'
            sv = _esc(q or '')
            search_html = f'<div class="search-box"><form method="GET" action="/browse"><input type="text" name="q" placeholder="Search links..." value="{sv}"><input type="hidden" name="sort" value="{_esc(sort)}"><button type="submit" class="btn btn-primary btn-sm">Search</button></form></div>'
            cards = '<div class="grid">'
            for lk in links:
                lid = lk['id']
                t = _esc(lk.get('title') or lk.get('url', ''))
                d = get_base_domain(lk.get('url', ''))
                og = lk.get('og_image_url', '')
                nc = lk.get('note_count', 0)
                sc = lk.get('direct_score', 0) or 0
                thumb = f'<img src="{_esc(og)}" class="thumb" alt="" loading="lazy">' if og else '<div class="thumb-placeholder">&#127760;</div>'
                pills = "".join(f'<span class="pill">{_esc(x.get("name", x.get("slug","")))}</span>' for x in lk.get('tags', [])[:4])
                cards += f'<a href="/link/{lid}" class="link-card">{thumb}<div class="body"><div class="card-title">{t}</div><div class="card-domain">{_esc(d)}</div><div class="card-pills">{pills}</div><div class="card-meta"><span>&#128221; {nc} notes</span><span>&#11088; {sc}</span></div></div></a>'
            cards += '</div>'
            if not links:
                cards = '<div style="text-align:center;padding:60px;color:#475569"><p style="font-size:40px;margin-bottom:12px">&#128279;</p><p>No links found.</p><p><a href="/add" class="btn btn-primary" style="margin-top:16px">Add the first one</a></p></div>'
            body = f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h1>Links ({len(links)})</h1><a href="/add" class="btn btn-primary">+ Add Link</a></div>{search_html}{sort_html}{tag_html}{cards}'
            return HTMLResponse(dark_page("Browse", body))
        except Exception as e:
            import traceback
            traceback.print_exc()
            return HTMLResponse(dark_page("Error", f'<div class="msg-err">Error: {_esc(str(e))}</div>'))
