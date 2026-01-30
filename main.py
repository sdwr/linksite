"""
Feed Ingestion System + Director â€” FastAPI Application
"""

import os
import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, Form, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Template
from supabase import create_client, Client
from pydantic import BaseModel

from ingest import (
    parse_youtube_channel, parse_rss_feed, parse_reddit_feed,
    parse_bluesky_feed, scrape_article, vectorize
)
from director import Director

load_dotenv()

supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

director = Director(supabase)


# â”€â”€â”€ Lifespan (Director startup/shutdown) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Director does NOT auto-start â€” use /admin/director/start
    print("[App] Ready. Director is stopped (use /admin/director/start)")
    yield
    director.stop()


app = FastAPI(title="Linksite", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# â”€â”€â”€ User Identity Middleware â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.middleware("http")
async def user_identity_middleware(request: Request, call_next):
    user_id = request.cookies.get("user_id")

    if not user_id:
        user_id = str(uuid.uuid4())
        # Lazy-create user in DB
        try:
            supabase.table("users").insert({"id": user_id}).execute()
        except Exception:
            pass  # May already exist

    request.state.user_id = user_id
    response = await call_next(request)

    # Set cookie if not present
    if not request.cookies.get("user_id"):
        response.set_cookie(
            key="user_id",
            value=user_id,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 365,  # 1 year
        )

    return response


# â”€â”€â”€ Vote Model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class VoteRequest(BaseModel):
    value: int  # 1 or -1


# â”€â”€â”€ API: Voting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/api/links/{link_id}/vote")
async def vote_on_link(link_id: int, vote: VoteRequest, request: Request):
    if vote.value not in (1, -1):
        raise HTTPException(400, "value must be 1 or -1")

    user_id = request.state.user_id

    # Cooldown check
    cooldown_sec = _get_weight("vote_cooldown_sec", 10)
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=cooldown_sec)).isoformat()
    recent = supabase.table("votes").select("id").eq(
        "user_id", user_id
    ).gte("created_at", cutoff).limit(1).execute()

    if recent.data:
        raise HTTPException(429, f"Cooldown: wait {cooldown_sec}s between votes")

    # Insert vote
    supabase.table("votes").insert({
        "user_id": user_id,
        "link_id": link_id,
        "value": vote.value,
    }).execute()

    return {"ok": True, "value": vote.value}


@app.get("/api/links/{link_id}/votes")
async def get_link_votes(link_id: int, request: Request):
    user_id = request.state.user_id

    # Total score
    all_votes = supabase.table("votes").select("value").eq("link_id", link_id).execute()
    score = sum(v["value"] for v in (all_votes.data or []))

    # My votes on this link
    my_votes = supabase.table("votes").select("value, created_at").eq(
        "link_id", link_id
    ).eq("user_id", user_id).order("created_at", desc=True).execute()

    return {
        "score": score,
        "my_votes_count": len(my_votes.data or []),
        "my_last_vote_at": my_votes.data[0]["created_at"] if my_votes.data else None,
    }


# â”€â”€â”€ API: /api/now â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/api/now")
async def api_now(request: Request):
    user_id = request.state.user_id
    now = datetime.now(timezone.utc)

    state = supabase.table("global_state").select("*").eq("id", 1).execute()
    if not state.data or not state.data[0].get("current_link_id"):
        return {"link": None, "message": "Director not running or no link selected"}

    gs = state.data[0]
    link_id = gs["current_link_id"]

    # Get current link
    link_resp = supabase.table("links").select(
        "id, url, title, meta_json, direct_score, feed_id"
    ).eq("id", link_id).execute()
    link = link_resp.data[0] if link_resp.data else None

    # Get tags via feed_tags
    tags = []
    if link and link.get("feed_id"):
        ft_resp = supabase.table("feed_tags").select(
            "tag_id"
        ).eq("feed_id", link["feed_id"]).execute()
        tag_ids = [ft["tag_id"] for ft in (ft_resp.data or [])]
        if tag_ids:
            tags_resp = supabase.table("tags").select(
                "name, slug"
            ).in_("id", tag_ids).execute()
            tags = tags_resp.data or []

    # Get satellites with reveal status
    satellites = gs.get("satellites") or []
    for sat in satellites:
        reveal_at = sat.get("reveal_at")
        if reveal_at:
            sat["revealed"] = now >= datetime.fromisoformat(
                reveal_at.replace("Z", "+00:00")
            )
        else:
            sat["revealed"] = True

    # Vote counts
    all_votes = supabase.table("votes").select("value").eq("link_id", link_id).execute()
    score = sum(v["value"] for v in (all_votes.data or []))

    my_votes = supabase.table("votes").select("created_at").eq(
        "link_id", link_id
    ).eq("user_id", user_id).order("created_at", desc=True).execute()

    # Timers
    rotation_ends = gs.get("rotation_ends_at")
    seconds_remaining = 0
    if rotation_ends:
        ends = datetime.fromisoformat(rotation_ends.replace("Z", "+00:00"))
        seconds_remaining = max(0, int((ends - now).total_seconds()))

    return {
        "link": link,
        "tags": tags,
        "satellites": satellites,
        "timers": {
            "started_at": gs.get("started_at"),
            "reveal_ends_at": gs.get("reveal_ends_at"),
            "rotation_ends_at": rotation_ends,
            "seconds_remaining": seconds_remaining,
        },
        "votes": {
            "score": score,
            "my_votes_count": len(my_votes.data or []),
            "my_last_vote_at": my_votes.data[0]["created_at"] if my_votes.data else None,
        },
        "selection_reason": gs.get("selection_reason"),
    }


# â”€â”€â”€ API: Tags â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/api/tags/top")
async def top_tags():
    resp = supabase.table("tags").select("*").order("score", desc=True).limit(20).execute()
    return resp.data or []


@app.get("/api/links/{link_id}/tags")
async def link_tags(link_id: int):
    link = supabase.table("links").select("feed_id").eq("id", link_id).execute()
    if not link.data or not link.data[0].get("feed_id"):
        return []
    feed_id = link.data[0]["feed_id"]
    ft = supabase.table("feed_tags").select("tag_id").eq("feed_id", feed_id).execute()
    tag_ids = [r["tag_id"] for r in (ft.data or [])]
    if not tag_ids:
        return []
    tags = supabase.table("tags").select("name, slug, score").in_("id", tag_ids).execute()
    return tags.data or []


# â”€â”€â”€ Admin: Director Controls â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/admin/director/start")
async def admin_director_start():
    director.start()
    return RedirectResponse(url="/admin?message=Director started", status_code=303)


@app.post("/admin/director/stop")
async def admin_director_stop():
    director.stop()
    return RedirectResponse(url="/admin?message=Director stopped", status_code=303)


@app.post("/admin/director/skip")
async def admin_director_skip():
    director.skip()
    return RedirectResponse(url="/admin?message=Skip requested", status_code=303)


@app.post("/admin/propagate")
async def admin_propagate():
    director._propagate_scores()
    return RedirectResponse(url="/admin?message=Scores propagated", status_code=303)


@app.get("/admin/director/status")
async def admin_director_status():
    state = supabase.table("global_state").select("*").eq("id", 1).execute()
    gs = state.data[0] if state.data else {}

    log = supabase.table("director_log").select("*").order(
        "selected_at", desc=True
    ).limit(10).execute()

    return {
        "running": director.running,
        "global_state": gs,
        "recent_log": log.data or [],
    }


# â”€â”€â”€ Admin: Feed Tag Management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/admin/feeds/{feed_id}/tags")
async def admin_add_feed_tag(feed_id: int, tag: str = Form(...)):
    slug = tag.lower().strip().replace(" ", "-")
    # Create or get tag
    existing = supabase.table("tags").select("id").eq("slug", slug).execute()
    if existing.data:
        tag_id = existing.data[0]["id"]
    else:
        resp = supabase.table("tags").insert({"name": tag.strip(), "slug": slug}).execute()
        tag_id = resp.data[0]["id"]

    # Create feed_tag
    try:
        supabase.table("feed_tags").insert({
            "feed_id": feed_id, "tag_id": tag_id
        }).execute()
    except Exception:
        pass  # Already exists

    return RedirectResponse(url=f"/admin?message=Tag '{tag}' added to feed {feed_id}", status_code=303)


@app.post("/admin/feeds/{feed_id}/tags/{slug}/delete")
async def admin_remove_feed_tag(feed_id: int, slug: str):
    tag = supabase.table("tags").select("id").eq("slug", slug).execute()
    if tag.data:
        supabase.table("feed_tags").delete().eq(
            "feed_id", feed_id
        ).eq("tag_id", tag.data[0]["id"]).execute()
    return RedirectResponse(url=f"/admin?message=Tag removed", status_code=303)


# â”€â”€â”€ Admin: Score Weights â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/api/weights")
async def get_weights():
    resp = supabase.table("score_weights").select("*").execute()
    return resp.data or []


@app.post("/api/weights/{key}")
async def update_weight(key: str, value: float = Form(...)):
    supabase.table("score_weights").update(
        {"value": value}
    ).eq("key", key).execute()
    return RedirectResponse(url="/admin?message=Weight updated", status_code=303)


# â”€â”€â”€ Helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_weight(key: str, default: float = 0.0) -> float:
    try:
        resp = supabase.table("score_weights").select("value").eq("key", key).execute()
        if resp.data:
            return float(resp.data[0]["value"])
    except Exception:
        pass
    return default


# â”€â”€â”€ Existing Admin/Feed Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# (keeping the existing admin dashboard, feed management, sync routes)

import threading
_active_syncs: dict = {}
_sync_all_cancel = threading.Event()


@app.get("/")
async def root():
    return RedirectResponse(url="/links")


@app.get("/links", response_class=HTMLResponse)
async def view_links(message: Optional[str] = None):
    try:
        response = supabase.table('links').select('*').order('created_at', desc=True).limit(50).execute()
        links = response.data or []
        stats = {'total': len(links)} if links else None
        warning = "No links found." if not links else None
        return HTMLResponse(f"<html><body><h1>Links ({len(links)})</h1>"
            + f"<p><a href='/admin'>Admin</a> | <a href='/api/now'>API Now</a> | <a href='/admin/director/status'>Director Status</a></p>"
            + "".join(f"<div><b>{l.get('title','?')}</b> â€” <a href='{l['url']}'>{l['url'][:80]}</a> (score: {l.get('direct_score',0)})</div>" for l in links)
            + "</body></html>")
    except Exception as e:
        return HTMLResponse(f"<h1>Error</h1><p>{e}</p>")


@app.post("/links/delete/{link_id}")
async def delete_link(link_id: int):
    supabase.table('links').delete().eq('id', link_id).execute()
    return RedirectResponse(url="/links?message=Deleted", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(message: Optional[str] = None, error: Optional[str] = None):
    try:
        feeds = supabase.table('feeds').select('*').order('created_at', desc=True).execute().data or []
        state = supabase.table("global_state").select("*").eq("id", 1).execute()
        gs = state.data[0] if state.data else {}

        html = f"""<html><body>
        <h1>Admin Dashboard</h1>
        <p>{f'<b style="color:green">{message}</b>' if message else ''}</p>
        <p>{f'<b style="color:red">{error}</b>' if error else ''}</p>

        <h2>Director</h2>
        <p>Status: <b>{'ðŸŸ¢ Running' if director.running else 'ðŸ”´ Stopped'}</b></p>
        <p>Current link: {gs.get('current_link_id', 'None')} | Reason: {gs.get('selection_reason', '-')}</p>
        <form method="POST" action="/admin/director/start" style="display:inline"><button>â–¶ Start</button></form>
        <form method="POST" action="/admin/director/stop" style="display:inline"><button>â¹ Stop</button></form>
        <form method="POST" action="/admin/director/skip" style="display:inline"><button>â­ Skip</button></form>
        <form method="POST" action="/admin/propagate" style="display:inline"><button>ðŸ“Š Propagate Scores</button></form>

        <h2>Feeds ({len(feeds)})</h2>
        <form method="POST" action="/admin/add-feed">
            <input name="url" placeholder="Feed URL" required>
            <select name="type"><option value="youtube">YouTube</option><option value="rss">RSS</option>
            <option value="reddit">Reddit</option><option value="bluesky">Bluesky</option>
            <option value="website">Website</option></select>
            <button>Add</button>
        </form>
        <form method="POST" action="/admin/sync"><button>ðŸ”„ Sync All</button></form>
        """

        for f in feeds:
            # Get feed tags
            ft = supabase.table("feed_tags").select("tag_id").eq("feed_id", f["id"]).execute()
            tag_ids = [t["tag_id"] for t in (ft.data or [])]
            feed_tag_names = []
            if tag_ids:
                tags = supabase.table("tags").select("name,slug").in_("id", tag_ids).execute()
                feed_tag_names = tags.data or []

            tags_html = " ".join(
                f'<span style="background:#eee;padding:2px 6px;border-radius:8px;font-size:12px">{t["name"]}'
                f' <a href="/admin/feeds/{f["id"]}/tags/{t["slug"]}/delete" style="color:red">Ã—</a></span>'
                for t in feed_tag_names
            )

            html += f"""
            <div style="border:1px solid #ddd;padding:10px;margin:5px 0">
                <b>[{f['type']}]</b> {f['url']}
                <br>Status: {f.get('status','idle')} | Links: {f.get('link_count',0)} | Trust: {f.get('trust_score',1.0):.2f}
                <br>Tags: {tags_html}
                <form method="POST" action="/admin/feeds/{f['id']}/tags" style="display:inline">
                    <input name="tag" placeholder="Add tag" size="10"><button>+</button>
                </form>
                <form method="POST" action="/admin/sync-feed/{f['id']}" style="display:inline"><button>Sync</button></form>
                <form method="POST" action="/admin/delete-feed/{f['id']}" style="display:inline"><button style="color:red">Delete</button></form>
            </div>"""

        html += "</body></html>"
        return HTMLResponse(html)
    except Exception as e:
        return HTMLResponse(f"<h1>Error</h1><p>{e}</p>")


@app.post("/admin/add-feed")
async def add_feed(url: str = Form(...), type: str = Form(...)):
    try:
        existing = supabase.table('feeds').select('id').eq('url', url).execute()
        if existing.data:
            return RedirectResponse(url="/admin?error=Feed exists", status_code=303)
        supabase.table('feeds').insert({
            'url': url, 'type': type, 'status': 'idle',
            'last_scraped_at': None, 'link_count': 0,
        }).execute()
        return RedirectResponse(url="/admin?message=Feed added", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/admin?error={e}", status_code=303)


@app.post("/admin/delete-feed/{feed_id}")
async def delete_feed(feed_id: int):
    supabase.table('links').delete().eq('feed_id', feed_id).execute()
    supabase.table('feed_tags').delete().eq('feed_id', feed_id).execute()
    supabase.table('feeds').delete().eq('id', feed_id).execute()
    return RedirectResponse(url="/admin?message=Feed deleted", status_code=303)


@app.post("/admin/sync")
async def sync_feeds(background_tasks: BackgroundTasks):
    _sync_all_cancel.clear()
    background_tasks.add_task(sync_all_feeds)
    return RedirectResponse(url="/admin?message=Sync started", status_code=303)


@app.post("/admin/sync-feed/{feed_id}")
async def sync_single_feed(feed_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(sync_feed_by_id, feed_id)
    return RedirectResponse(url="/admin?message=Syncing...", status_code=303)


@app.post("/admin/cancel-all")
async def cancel_all_syncs():
    _sync_all_cancel.set()
    for s in _active_syncs.values():
        s["cancel"] = True
    return RedirectResponse(url="/admin?message=Cancelled", status_code=303)


# â”€â”€â”€ Sync Engine (unchanged from before) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def sync_feed_by_id(feed_id: int):
    try:
        resp = supabase.table('feeds').select('*').eq('id', feed_id).execute()
        if not resp.data:
            return
        await process_single_feed(resp.data[0])
    except Exception as e:
        print(f"Error syncing feed {feed_id}: {e}")
        supabase.table('feeds').update({'status': 'error', 'last_error': str(e)[:500]}).eq('id', feed_id).execute()


async def sync_all_feeds():
    resp = supabase.table('feeds').select('*').execute()
    for feed in (resp.data or []):
        if _sync_all_cancel.is_set():
            break
        await process_single_feed(feed)


async def process_single_feed(feed: dict):
    feed_id = feed['id']
    _active_syncs[feed_id] = {"cancel": False}
    supabase.table('feeds').update({'status': 'syncing', 'last_error': None}).eq('id', feed_id).execute()
    try:
        ft = feed['type']
        if ft == 'youtube':
            items = parse_youtube_channel(feed['url'])
        elif ft == 'rss':
            items = parse_rss_feed(feed['url'])
        elif ft == 'reddit':
            items = parse_reddit_feed(feed['url'])
        elif ft == 'bluesky':
            items = parse_bluesky_feed(feed['url'])
        elif ft == 'website':
            data = scrape_article(feed['url'])
            items = [{'url': feed['url'], 'title': data.get('title',''), 'content': data.get('description',''), 'meta': {'type':'website'}}]
        else:
            items = []

        ingested = 0
        for item in items:
            if _active_syncs.get(feed_id, {}).get("cancel"):
                break
            url = item.get('url', '')
            if not url:
                continue
            existing = supabase.table('links').select('id').eq('url', url).execute()
            if existing.data:
                continue
            try:
                text = f"{item.get('title','')}. {item.get('content','')}"
                vector = vectorize(text[:5000])
                supabase.table('links').insert({
                    'url': url, 'title': item.get('title',''),
                    'content': (item.get('content','') or '')[:10000],
                    'meta_json': item.get('meta', {}),
                    'content_vector': vector, 'feed_id': feed_id,
                }).execute()
                ingested += 1
            except Exception as e:
                print(f"  Error ingesting {url}: {e}")

        link_count = len(supabase.table('links').select('id').eq('feed_id', feed_id).execute().data or [])
        supabase.table('feeds').update({
            'status': 'idle', 'last_scraped_at': datetime.now(timezone.utc).isoformat(),
            'last_error': None, 'link_count': link_count,
        }).eq('id', feed_id).execute()
        print(f"Feed {feed_id}: {ingested} new links")
    except Exception as e:
        print(f"Error syncing feed {feed_id}: {e}")
        supabase.table('feeds').update({'status': 'error', 'last_error': str(e)[:500]}).eq('id', feed_id).execute()
    finally:
        _active_syncs.pop(feed_id, None)


# â”€â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('PORT', 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
