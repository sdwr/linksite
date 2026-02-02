"""
Scratchpad HTML pages for Linksite.
API routes are in scratchpad_api.py — this file handles /add, /browse, /link/{id}.
"""

import re
from typing import Optional, List
from urllib.parse import urlparse
from datetime import datetime, timezone
from fastapi import BackgroundTasks, Form, HTTPException
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
    """Normalize a URL: add https:// if missing, strip www."""
    url = url.strip()
    if not url:
        return url
    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    # Strip www.
    parsed = urlparse(url)
    host = parsed.netloc or ''
    if host.startswith('www.'):
        host = host[4:]
        url = parsed._replace(netloc=host).geturl()
    return url


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
"""


def dark_nav():
    return """<div class="topbar">
        <a href="/browse" class="brand">&#128279; Linksite</a>
        <a href="/browse">Browse</a>
        <a href="/add">Check Link</a>
    </div>"""


def dark_page(title, body):
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
</body></html>"""


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
        """Background task to fetch external discussions."""
        import threading
        def _run():
            fetch_and_save_external_discussions(link_id, url)
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
        # External Discussions
        ext_discussions = get_external_discussions(link_id)
        ext_disc_html = '<div class="card">'
        ext_disc_html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">'
        ext_disc_html += '<h2 style="margin-bottom:0">External Discussions</h2>'
        ext_disc_html += f'<form method="POST" action="/link/{link_id}/refresh-discussions" style="margin:0"><button type="submit" class="refresh-btn">&#8635; Refresh</button></form>'
        ext_disc_html += '</div>'
        
        if ext_discussions:
            for d in ext_discussions:
                platform = d.get('platform', '')
                icon = '&#129412;' if platform == 'hackernews' else '&#129302;'  # Y for HN, robot for reddit
                platform_label = 'Hacker News' if platform == 'hackernews' else f'r/{d.get("subreddit", "reddit")}'
                d_title = _esc(d.get('title', 'Discussion'))
                d_url = _esc(d.get('external_url', '#'))
                d_score = d.get('score', 0) or 0
                d_comments = d.get('num_comments', 0) or 0
                ext_disc_html += f'<a href="{d_url}" target="_blank" class="ext-disc" style="text-decoration:none">'
                ext_disc_html += f'<div class="platform-icon">{icon}</div>'
                ext_disc_html += f'<div class="disc-info"><div class="disc-title">{d_title}</div>'
                ext_disc_html += f'<div class="disc-meta">{_esc(platform_label)}</div></div>'
                ext_disc_html += f'<div class="disc-stats"><span>&#9650; {d_score}</span><span>&#128172; {d_comments}</span></div>'
                ext_disc_html += '</a>'
        else:
            ext_disc_html += '<p style="color:#475569;font-size:13px;padding:4px 0">No external discussions found yet. Click refresh to check HN and Reddit.</p>'
        
        ext_disc_html += '</div>'

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
        return RedirectResponse(url=f"/link/{link_id}?message=Link+saved!+Content+being+extracted...", status_code=303)

    # ========== GET /link/{id} — Detail page ==========
    @app.get("/link/{link_id}", response_class=HTMLResponse)
    async def page_link_detail(link_id: int, message: Optional[str] = None, error: Optional[str] = None):
        resp = supabase.table('links').select('*').eq('id', link_id).execute()
        if not resp.data:
            return HTMLResponse(dark_page("Not Found", '<div class="msg-err">Link not found.</div>'))

        link = _enrich(resp.data[0])
        related = _find_related(link_id, 6)

        msgs = ""
        if message:
            msgs += f'<div class="msg-ok">{_esc(message)}</div>'
        if error:
            msgs += f'<div class="msg-err">{_esc(error)}</div>'

        title = _esc(link.get('title') or link.get('url', ''))
        url = link.get('url', '')
        domain = get_base_domain(url)
        og_img = link.get('og_image_url') or link.get('screenshot_url') or ''
        img_html = f'<img src="{_esc(og_img)}" class="img-preview" alt="preview">' if og_img else ""
        score = link.get('direct_score', 0) or 0

        # Tags as pills with "+" button at the end
        tags_html = '<div class="tags-row">'
        for t in link.get('tags', []):
            sl = _esc(t.get('slug', ''))
            nm = _esc(t.get('name', sl))
            tags_html += f'<span class="pill">{nm}<a href="/link/{link_id}/remove-tag/{sl}" class="x">&times;</a></span>'
        tags_html += f'''<a href="#" class="tag-add-btn" onclick="document.getElementById('tag-form').classList.toggle('show');this.style.display='none';document.getElementById('tag-input').focus();return false;">+</a>
        <form id="tag-form" class="tag-form" method="POST" action="/link/{link_id}/add-tags">
            <input id="tag-input" type="text" name="tags" placeholder="tag1, tag2" required>
            <button type="submit">add</button>
        </form>'''
        tags_html += '</div>'
        if not link.get('tags'):
            tags_html = f'''<div class="tags-row">
                <span style="color:#475569;font-size:13px;margin-right:8px">No tags yet</span>
                <a href="#" class="tag-add-btn" onclick="document.getElementById('tag-form').classList.toggle('show');this.style.display='none';document.getElementById('tag-input').focus();return false;">+</a>
                <form id="tag-form" class="tag-form" method="POST" action="/link/{link_id}/add-tags">
                    <input id="tag-input" type="text" name="tags" placeholder="tag1, tag2" required>
                    <button type="submit">add</button>
                </form>
            </div>'''

        # Parent link
        parent_html = ""
        if link.get('parent'):
            p = link['parent']
            parent_html = f'<div style="margin-bottom:12px"><span style="color:#64748b;font-size:13px">Part of:</span> <a href="/link/{p["id"]}">{_esc(p.get("title") or p.get("url"))}</a></div>'

        # Comments section — reddit style
        comments_html = ""
        notes = link.get('notes', [])

        # Comment input at top
        comments_html += f'''<div class="comment-input">
            <form method="POST" action="/link/{link_id}/add-note" style="display:flex;gap:10px;width:100%">
                <textarea name="text" placeholder="Add a comment..." required rows="1"
                    onfocus="this.rows=3" onblur="if(!this.value)this.rows=1"
                    onkeydown="if(event.key==='Enter'&&!event.shiftKey){{event.preventDefault();this.form.submit()}}"></textarea>
                <input type="hidden" name="author" value="anon">
            </form>
        </div>'''

        # Comments list
        if notes:
            for n in notes:
                na = _esc(n.get('author', 'anonymous'))
                nt = _esc(n.get('text', ''))
                ta = time_ago(n.get('created_at', ''))
                comments_html += f'''<div class="comment">
                    <div class="vote-col">
                        <button class="vote-btn up" title="Upvote">&#9650;</button>
                        <span class="vote-score">&middot;</span>
                        <button class="vote-btn down" title="Downvote">&#9660;</button>
                    </div>
                    <div class="comment-body">
                        <div class="comment-meta"><strong>{na}</strong> &middot; {ta}</div>
                        <div class="comment-text">{nt}</div>
                    </div>
                </div>'''
        else:
            comments_html += '<p style="color:#475569;font-size:13px;padding:8px 0">No comments yet. Start the discussion!</p>'

        # Related links
        related_html = ""
        for r in related:
            rt = _esc(r.get('title') or r.get('url', ''))
            rd = get_base_domain(r.get('url', ''))
            rid = r.get('id')
            related_html += f'<a href="/link/{rid}" class="related-link"><span class="r-title">{rt}</span><br><span class="r-url">{_esc(rd)}</span></a>'
        if not related_html:
            related_html = '<p style="color:#475569;font-size:13px">No related links found.</p>'

        # External Discussions
        ext_discussions = get_external_discussions(link_id)
        ext_disc_html = '<div class="card">'
        ext_disc_html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">'
        ext_disc_html += '<h2 style="margin-bottom:0">External Discussions</h2>'
        ext_disc_html += f'<form method="POST" action="/link/{link_id}/refresh-discussions" style="margin:0"><button type="submit" class="refresh-btn">&#8635; Refresh</button></form>'
        ext_disc_html += '</div>'
        
        if ext_discussions:
            for d in ext_discussions:
                platform = d.get('platform', '')
                icon = '&#129412;' if platform == 'hackernews' else '&#129302;'  # Y for HN, robot for reddit
                platform_label = 'Hacker News' if platform == 'hackernews' else f'r/{d.get("subreddit", "reddit")}'
                d_title = _esc(d.get('title', 'Discussion'))
                d_url = _esc(d.get('external_url', '#'))
                d_score = d.get('score', 0) or 0
                d_comments = d.get('num_comments', 0) or 0
                ext_disc_html += f'<a href="{d_url}" target="_blank" class="ext-disc" style="text-decoration:none">'
                ext_disc_html += f'<div class="platform-icon">{icon}</div>'
                ext_disc_html += f'<div class="disc-info"><div class="disc-title">{d_title}</div>'
                ext_disc_html += f'<div class="disc-meta">{_esc(platform_label)}</div></div>'
                ext_disc_html += f'<div class="disc-stats"><span>&#9650; {d_score}</span><span>&#128172; {d_comments}</span></div>'
                ext_disc_html += '</a>'
        else:
            ext_disc_html += '<p style="color:#475569;font-size:13px;padding:4px 0">No external discussions found yet. Click refresh to check HN and Reddit.</p>'
        
        ext_disc_html += '</div>'

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
            <div style="color:#64748b;font-size:13px;margin-bottom:12px">
                <a href="/browse?q={_esc(domain)}" style="color:#64748b">{_esc(domain)}</a>
                &middot; {time_ago(link.get('created_at'))}
                {f' &middot; by {_esc(link.get("submitted_by") or "")}' if link.get("submitted_by") and link["submitted_by"] != "web" else ''}
            </div>
            {img_html}
            <div style="display:flex;align-items:baseline;gap:0;flex-wrap:wrap;margin-top:8px">
                <span style="color:#64748b;font-size:13px;margin-right:8px;font-weight:500;white-space:nowrap">Tags:</span>
                {tags_html}
            </div>
        </div>

        <div class="card">
            {comments_html}
        </div>

        {ext_disc_html}

        <div class="card">
            <h2>Related Links</h2>
            {related_html}
        </div>"""
        return HTMLResponse(dark_page(title, body))

    # ========== POST /link/{id}/add-note ==========
    @app.post("/link/{link_id}/add-note")
    async def page_add_note(link_id: int, text: str = Form(...), author: str = Form("anon")):
        author = author.strip() or "anon"
        supabase.table('notes').insert({'link_id': link_id, 'author': author, 'text': text.strip()}).execute()
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

    # ========== GET /browse ==========
    @app.get("/browse", response_class=HTMLResponse)
    async def page_browse(tag: Optional[str] = None, sort: Optional[str] = "recent", q: Optional[str] = None):
        try:
            all_tags_resp = supabase.table('tags').select('slug, name').order('name').execute()
            all_tags = all_tags_resp.data or []

            # Fetch links
            if tag:
                tag_resp = supabase.table('tags').select('id').eq('slug', tag).execute()
                if tag_resp.data:
                    tag_id = tag_resp.data[0]['id']
                    lt_resp = supabase.table('link_tags').select('link_id').eq('tag_id', tag_id).execute()
                    link_ids = [lt['link_id'] for lt in (lt_resp.data or [])]
                    if link_ids:
                        qr = supabase.table('links').select(
                            'id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by'
                        ).in_('id', link_ids)
                    else:
                        qr = None
                else:
                    qr = None
            elif q:
                qr = supabase.table('links').select(
                    'id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by'
                ).or_(f'title.ilike.%{q}%,url.ilike.%{q}%,description.ilike.%{q}%')
            else:
                qr = supabase.table('links').select(
                    'id, url, title, og_image_url, description, direct_score, created_at, source, submitted_by'
                ).neq('source', 'auto-parent')

            links = []
            if qr is not None:
                if sort == "score":
                    qr = qr.order('direct_score', desc=True)
                else:
                    qr = qr.order('created_at', desc=True)
                links = (qr.limit(60).execute()).data or []

            # Batch-enrich: tags and note counts in 3 queries instead of 152
            if links:
                link_ids = [lk['id'] for lk in links]

                # 1) All notes for these links (just ids for counting)
                all_notes = supabase.table('notes').select('link_id').in_('link_id', link_ids).execute()
                note_counts = {}
                for n in (all_notes.data or []):
                    note_counts[n['link_id']] = note_counts.get(n['link_id'], 0) + 1

                # 2) All link_tags for these links
                all_lt = supabase.table('link_tags').select('link_id, tag_id').in_('link_id', link_ids).execute()
                link_tag_map = {}
                all_tag_ids = set()
                for lt in (all_lt.data or []):
                    link_tag_map.setdefault(lt['link_id'], []).append(lt['tag_id'])
                    all_tag_ids.add(lt['tag_id'])

                # 3) All tag names at once
                tag_name_map = {}
                if all_tag_ids:
                    all_tags_data = supabase.table('tags').select('id, slug, name').in_('id', list(all_tag_ids)).execute()
                    for t in (all_tags_data.data or []):
                        tag_name_map[t['id']] = {'slug': t['slug'], 'name': t['name']}

                # Apply to each link
                for link in links:
                    lid = link['id']
                    link['note_count'] = note_counts.get(lid, 0)
                    link['tags'] = [tag_name_map[tid] for tid in link_tag_map.get(lid, []) if tid in tag_name_map]

            if sort == "noted":
                links.sort(key=lambda x: x.get('note_count', 0), reverse=True)

            # Sort links
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
            </div>'''

            # Tag filter bar
            tag_html = '<div class="sort-bar"><span style="color:#64748b;font-size:13px">Tags:</span>'
            act_all = ' active' if not tag else ''
            tag_html += f'<a href="/browse?sort={sort}" class="{act_all}">All</a>'
            for t in all_tags:
                ac = ' active' if tag == t['slug'] else ''
                tag_html += f'<a href="/browse?tag={_esc(t["slug"])}&sort={sort}" class="{ac}">{_esc(t["name"])}</a>'
            tag_html += '</div>'

            # Cards
            cards = '<div class="grid">'
            for lk in links:
                lid = lk['id']
                t = _esc(lk.get('title') or lk.get('url', ''))
                d = get_base_domain(lk.get('url', ''))
                og = lk.get('og_image_url', '')
                nc = lk.get('note_count', 0)
                sc = lk.get('direct_score', 0) or 0

                thumb = f'<img src="{_esc(og)}" class="thumb" alt="" loading="lazy">' if og else '<div class="thumb-placeholder">&#127760;</div>'
                pills = "".join(f'<span class="pill-sm">{_esc(x.get("name", x.get("slug","")))}</span>' for x in lk.get('tags', [])[:4])

                cards += f'''<a href="/link/{lid}" class="link-card">
                    {thumb}
                    <div class="body">
                        <div class="card-title">{t}</div>
                        <div class="card-domain">{_esc(d)}</div>
                        <div class="card-pills">{pills}</div>
                        <div class="card-meta">
                            <span>&#128172; {nc}</span>
                            <span>&#11088; {sc}</span>
                        </div>
                    </div>
                </a>'''
            cards += '</div>'

            if not links:
                cards = '''<div class="empty-state">
                    <div class="icon">&#128279;</div>
                    <p>No links found.</p>
                    <p style="margin-top:12px"><a href="/add" class="btn btn-primary">Add the first one</a></p>
                </div>'''

            # Filter banner when searching by domain/query
            filter_html = ''
            if q:
                filter_html = f'''<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;padding:10px 16px;background:#1e293b;border:1px solid #334155;border-radius:8px">
                    <span style="color:#94a3b8;font-size:14px">Showing links from <strong style="color:#e2e8f0">{_esc(q)}</strong></span>
                    <a href="/browse" style="color:#64748b;font-size:18px;line-height:1;margin-left:auto;text-decoration:none" title="Clear filter">&times;</a>
                </div>'''

            body = f'''{filter_html}{sort_html}{tag_html}{cards}'''

            return HTMLResponse(dark_page("Browse", body))
        except Exception as e:
            import traceback
            traceback.print_exc()
            return HTMLResponse(dark_page("Error", f'<div class="msg-err">Error: {_esc(str(e))}</div>'))
