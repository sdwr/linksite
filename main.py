"""
Feed Ingestion System + Director -- FastAPI Application
"""

import os
import json
import uuid
import asyncio
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, Form, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
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

# ============================================================
# SSE Broadcast Infrastructure
# ============================================================

connected_clients: set[asyncio.Queue] = set()
recent_actions: deque = deque(maxlen=50)  # ring buffer of recent user actions


def broadcast_event(event: dict):
    """Push an event to all connected SSE clients."""
    for q in list(connected_clients):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # drop if client is too slow


def record_action(action: dict):
    """Record an action for recent_actions feed and broadcast it."""
    action["_ts"] = time.time()
    recent_actions.append(action)
    broadcast_event(action)


# ============================================================
# Director Setup
# ============================================================

director = Director(supabase, broadcast_fn=broadcast_event)


# --- Lifespan (Director startup/shutdown) ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Director does NOT auto-start -- use /admin/director/start
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


# --- User Identity Middleware ---

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


# --- Request Models ---

class VoteRequest(BaseModel):
    value: int  # 1 or -1


class NominateRequest(BaseModel):
    user_id: Optional[str] = None  # optional override; defaults to cookie


# ============================================================
# HTML Helpers
# ============================================================

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f5f5f5; color: #222; line-height: 1.5; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
nav { background: #1e293b; padding: 12px 24px; display: flex; gap: 24px; align-items: center; }
nav a { color: #e2e8f0; font-weight: 600; font-size: 15px; }
nav a:hover { color: #fff; text-decoration: none; }
nav .brand { color: #38bdf8; font-size: 18px; font-weight: 700; margin-right: auto; }
.container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
.card h2 { margin-bottom: 12px; font-size: 18px; color: #1e293b; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }
.msg-ok { background: #dcfce7; color: #166534; padding: 10px 16px; border-radius: 6px; margin-bottom: 16px; }
.msg-err { background: #fee2e2; color: #991b1b; padding: 10px 16px; border-radius: 6px; margin-bottom: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; padding: 8px 10px; background: #f8fafc; border-bottom: 2px solid #e2e8f0; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; }
td { padding: 8px 10px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
tr:hover td { background: #f8fafc; }
.truncate { max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: inline-block; vertical-align: bottom; }
button, .btn { cursor: pointer; padding: 6px 14px; border-radius: 6px; border: 1px solid #d1d5db;
               background: #fff; font-size: 13px; font-weight: 500; }
button:hover, .btn:hover { background: #f1f5f9; }
.btn-primary { background: #2563eb; color: #fff; border-color: #2563eb; }
.btn-primary:hover { background: #1d4ed8; }
.btn-danger { color: #dc2626; border-color: #fca5a5; }
.btn-danger:hover { background: #fef2f2; }
.btn-sm { padding: 3px 10px; font-size: 12px; }
.inline-form { display: inline-block; margin: 0 4px; }
input[type="text"], input[type="url"], input[type="number"], select {
    padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px; }
.status-running { color: #16a34a; font-weight: 700; }
.status-stopped { color: #dc2626; font-weight: 700; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
.tag { display: inline-block; background: #e0e7ff; color: #3730a3; padding: 2px 8px; border-radius: 10px; font-size: 12px; margin: 2px; }
.tag .del { color: #dc2626; margin-left: 4px; font-weight: 700; }
.kv { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #f1f5f9; font-size: 14px; }
.kv .label { color: #64748b; }
.feed-box { border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-bottom: 10px; background: #fafbfc; }
.filter-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.filter-bar a { padding: 4px 12px; border-radius: 14px; font-size: 13px; background: #e2e8f0; color: #334155; }
.filter-bar a.active { background: #2563eb; color: #fff; }
.log-entry { font-size: 13px; padding: 4px 0; border-bottom: 1px solid #f1f5f9; color: #475569; }
"""

def _nav():
    return """<nav>
        <span class="brand">Linksite</span>
        <a href="/links">Links</a>
        <a href="/admin">Admin</a>
        <a href="/api/now">API Status</a>
        <a href="/" style="margin-left:auto;background:#2563eb;color:#fff;padding:6px 16px;border-radius:6px;font-size:14px;">Frontend &#10132;</a>
    </nav>"""


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Linksite</title>
<style>{_CSS}</style>
</head>
<body>
{_nav()}
<div class="container">
{body}
</div>
</body>
</html>"""


def _messages(message: Optional[str], error: Optional[str] = None) -> str:
    parts = []
    if message:
        parts.append(f'<div class="msg-ok">{_esc(message)}</div>')
    if error:
        parts.append(f'<div class="msg-err">{_esc(error)}</div>')
    return "".join(parts)


def _esc(s: str) -> str:
    """Basic HTML escaping."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ============================================================
# SSE Stream: GET /api/stream
# ============================================================

async def get_stream_state() -> dict:
    """Build the full state snapshot for SSE heartbeat."""
    now = datetime.now(timezone.utc)

    state = supabase.table("global_state").select("*").eq("id", 1).execute()
    gs = state.data[0] if state.data else {}

    # Featured link
    featured = None
    link_id = gs.get("current_link_id")
    if link_id:
        link_resp = supabase.table("links").select(
            "id, url, title, feed_id"
        ).eq("id", link_id).execute()
        link_data = link_resp.data[0] if link_resp.data else None

        # Get feed name
        feed_name = None
        if link_data and link_data.get("feed_id"):
            feed_resp = supabase.table("feeds").select("url, type").eq("id", link_data["feed_id"]).execute()
            if feed_resp.data:
                u = feed_resp.data[0].get("url", "")
                feed_name = u.split("/")[-1] or u.split("/")[-2] if "/" in u else u

        rotation_ends = gs.get("rotation_ends_at")
        started_at = gs.get("started_at")
        time_remaining = 0
        total_duration = int(_get_weight("rotation_default_sec", 120))
        if rotation_ends:
            ends = datetime.fromisoformat(rotation_ends.replace("Z", "+00:00"))
            time_remaining = max(0, (ends - now).total_seconds())

        if link_data:
            featured = {
                "link": {
                    "id": link_data["id"],
                    "title": link_data.get("title", ""),
                    "url": link_data.get("url", ""),
                    "feed_name": feed_name,
                },
                "time_remaining_sec": round(time_remaining, 1),
                "total_duration_sec": total_duration,
                "reason": gs.get("selection_reason", "unknown"),
                "started_at": started_at,
            }

    # Satellites with reveal status and nomination counts
    satellites_raw = gs.get("satellites") or []
    satellites = []
    rotation_id = gs.get("started_at", "")  # use started_at as rotation identifier

    for sat in satellites_raw:
        reveal_at = sat.get("reveal_at")
        revealed = True
        if reveal_at:
            revealed = now >= datetime.fromisoformat(reveal_at.replace("Z", "+00:00"))

        # Get nomination count for this satellite in current rotation
        nom_count = 0
        sat_link_id = sat.get("link_id")
        if sat_link_id:
            try:
                nom_resp = supabase.table("nominations").select("id").eq(
                    "link_id", sat_link_id
                ).eq("rotation_id", rotation_id).execute()
                nom_count = len(nom_resp.data or [])
            except Exception:
                pass

        satellites.append({
            "id": sat.get("link_id"),
            "title": sat.get("title", ""),
            "url": sat.get("url", ""),
            "position": sat.get("position", ""),
            "label": sat.get("label", ""),
            "revealed": revealed,
            "nominations": nom_count,
        })

    # Recent actions (from in-memory deque)
    now_ts = time.time()
    recent = []
    for action in list(recent_actions):
        ago = now_ts - action.get("_ts", now_ts)
        entry = {k: v for k, v in action.items() if k != "_ts"}
        entry["ago_sec"] = round(ago, 1)
        recent.append(entry)
    # Only last 20
    recent = recent[-20:]

    return {
        "type": "state",
        "featured": featured,
        "satellites": satellites,
        "recent_actions": recent,
        "viewer_count": len(connected_clients),
        "server_time": now.isoformat(),
    }


@app.get("/api/stream")
async def event_stream():
    """Server-Sent Events endpoint. Pushes state every 2s or immediate events."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    connected_clients.add(queue)

    async def generate():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat: send full state
                    state = await get_stream_state()
                    yield f"data: {json.dumps(state)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            connected_clients.discard(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# API: Reactions (vote/react)
# ============================================================

@app.post("/api/links/{link_id}/react")
async def react_to_link(link_id: int, vote: VoteRequest, request: Request):
    """React to a link: +1 (like) or -1 (dislike). Affects score and timer."""
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

    # Update direct_score on the link
    all_votes = supabase.table("votes").select("value").eq("link_id", link_id).execute()
    new_score = sum(v["value"] for v in (all_votes.data or []))
    supabase.table("links").update({"direct_score": new_score}).eq("id", link_id).execute()

    # Broadcast reaction event
    record_action({
        "type": "react",
        "link_id": link_id,
        "value": vote.value,
        "user_id": user_id[:12],  # truncate for privacy
    })

    return {"ok": True, "value": vote.value, "new_score": new_score}


# Backward-compat alias
@app.post("/api/links/{link_id}/vote")
async def vote_on_link(link_id: int, vote: VoteRequest, request: Request):
    """Alias for /api/links/{link_id}/react (backward compat)."""
    return await react_to_link(link_id, vote, request)


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


# ============================================================
# API: Nominations
# ============================================================

@app.post("/api/links/{link_id}/nominate")
async def nominate_link(link_id: int, body: NominateRequest, request: Request):
    """Nominate a satellite link to be featured next."""
    user_id = body.user_id or request.state.user_id

    # Get current rotation_id (started_at from global_state)
    state = supabase.table("global_state").select("started_at, satellites").eq("id", 1).execute()
    gs = state.data[0] if state.data else {}
    rotation_id = gs.get("started_at", "")

    if not rotation_id:
        raise HTTPException(400, "No active rotation")

    # Check that link_id is actually a satellite in the current rotation
    satellites = gs.get("satellites") or []
    sat_ids = [s.get("link_id") for s in satellites]
    if link_id not in sat_ids:
        raise HTTPException(400, "Link is not a current satellite")

    # Check if user already nominated in this rotation
    existing = supabase.table("nominations").select("id").eq(
        "user_id", user_id
    ).eq("rotation_id", rotation_id).execute()

    if existing.data:
        # Update existing nomination to new link
        supabase.table("nominations").update({
            "link_id": link_id,
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        # Insert new nomination
        supabase.table("nominations").insert({
            "link_id": link_id,
            "user_id": user_id,
            "rotation_id": rotation_id,
        }).execute()

    # Apply +0.5 score boost to the nominated link
    link_resp = supabase.table("links").select("direct_score").eq("id", link_id).execute()
    if link_resp.data:
        current_score = link_resp.data[0].get("direct_score", 0) or 0
        supabase.table("links").update({
            "direct_score": current_score + 0.5
        }).eq("id", link_id).execute()

    # Get nomination count for this link in this rotation
    nom_resp = supabase.table("nominations").select("id").eq(
        "link_id", link_id
    ).eq("rotation_id", rotation_id).execute()
    nom_count = len(nom_resp.data or [])

    # Broadcast nomination event
    record_action({
        "type": "nominate",
        "link_id": link_id,
        "user_id": user_id[:12],
    })

    return {"ok": True, "nominations": nom_count}


@app.get("/api/links/{link_id}/nominations")
async def get_link_nominations(link_id: int):
    """Get nomination count for a link in the current rotation."""
    state = supabase.table("global_state").select("started_at").eq("id", 1).execute()
    gs = state.data[0] if state.data else {}
    rotation_id = gs.get("started_at", "")

    nom_resp = supabase.table("nominations").select("id").eq(
        "link_id", link_id
    ).eq("rotation_id", rotation_id).execute()

    return {"link_id": link_id, "nominations": len(nom_resp.data or [])}


# ============================================================
# API: /api/now
# ============================================================

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

    # Get satellites with reveal status and nomination counts
    satellites = gs.get("satellites") or []
    rotation_id = gs.get("started_at", "")
    for sat in satellites:
        reveal_at = sat.get("reveal_at")
        if reveal_at:
            sat["revealed"] = now >= datetime.fromisoformat(
                reveal_at.replace("Z", "+00:00")
            )
        else:
            sat["revealed"] = True

        # Add nomination count
        sat_link_id = sat.get("link_id")
        if sat_link_id:
            try:
                nom_resp = supabase.table("nominations").select("id").eq(
                    "link_id", sat_link_id
                ).eq("rotation_id", rotation_id).execute()
                sat["nominations"] = len(nom_resp.data or [])
            except Exception:
                sat["nominations"] = 0

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
        "viewer_count": len(connected_clients),
    }


# ============================================================
# API: Tags
# ============================================================

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


# ============================================================
# Admin: Director Controls
# ============================================================

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


# ============================================================
# Admin: Feed Tag Management
# ============================================================

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


# ============================================================
# Admin: Score Weights
# ============================================================

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


# ============================================================
# Helper
# ============================================================

def _get_weight(key: str, default: float = 0.0) -> float:
    try:
        resp = supabase.table("score_weights").select("value").eq("key", key).execute()
        if resp.data:
            return float(resp.data[0]["value"])
    except Exception:
        pass
    return default


# ============================================================
# HTML Pages
# ============================================================

import threading
_active_syncs: dict = {}
_sync_all_cancel = threading.Event()


@app.get("/")
async def root():
    return RedirectResponse(url="/links")


@app.get("/links", response_class=HTMLResponse)
async def view_links(message: Optional[str] = None, feed_id: Optional[int] = None):
    try:
        # Get all feeds for the filter bar
        feeds_resp = supabase.table('feeds').select('id, url, type').order('id').execute()
        feeds = feeds_resp.data or []

        # Build feed name map
        feed_map = {}
        for f in feeds:
            # Derive a short name from the URL
            u = f.get("url", "")
            name = u.split("/")[-1] or u.split("/")[-2] if "/" in u else u
            if len(name) > 30:
                name = name[:30] + "..."
            feed_map[f["id"]] = {"name": name, "type": f.get("type", "?")}

        # Fetch links (optionally filtered by feed)
        query = supabase.table('links').select('id, url, title, direct_score, times_shown, feed_id, created_at').order('created_at', desc=True).limit(200)
        if feed_id:
            query = query.eq('feed_id', feed_id)
        response = query.execute()
        links = response.data or []

        # --- Filter bar ---
        filter_html = '<div class="filter-bar"><span style="font-size:13px;color:#64748b;">Filter:</span>'
        active_all = ' active' if not feed_id else ''
        filter_html += f'<a href="/links" class="{active_all}">All</a>'
        for f in feeds:
            active_cls = ' active' if feed_id == f["id"] else ''
            fname = feed_map[f["id"]]["name"]
            filter_html += f'<a href="/links?feed_id={f["id"]}" class="{active_cls}">{_esc(fname)}</a>'
        filter_html += '</div>'

        # --- Table ---
        rows = ""
        for l in links:
            lid = l.get("id", "?")
            title = _esc(l.get("title") or "(untitled)")
            url = l.get("url", "")
            url_display = _esc(url[:70] + ("..." if len(url) > 70 else ""))
            fid = l.get("feed_id")
            fname = _esc(feed_map.get(fid, {}).get("name", "-")) if fid else "-"
            score = l.get("direct_score", 0) or 0
            shown = l.get("times_shown", 0) or 0
            score_cls = 'color:#16a34a' if score > 0 else ('color:#dc2626' if score < 0 else 'color:#94a3b8')
            rows += f"""<tr>
                <td><strong>{title}</strong><br><a href="{_esc(url)}" target="_blank" class="truncate">{url_display}</a></td>
                <td>{fname}</td>
                <td style="{score_cls};font-weight:600;text-align:center">{score}</td>
                <td style="text-align:center">{shown}</td>
                <td>
                    <form method="POST" action="/links/delete/{lid}" class="inline-form"
                          onsubmit="return confirm('Delete this link?')">
                        <button class="btn-sm btn-danger" type="submit">&times;</button>
                    </form>
                </td>
            </tr>"""

        body = _messages(message)
        body += f'<h1 style="margin-bottom:12px">Links ({len(links)})</h1>'
        body += filter_html
        body += f"""<div class="card" style="padding:0;overflow-x:auto">
            <table>
            <thead><tr>
                <th>Title / URL</th>
                <th>Feed</th>
                <th style="text-align:center">Score</th>
                <th style="text-align:center">Shown</th>
                <th style="width:50px"></th>
            </tr></thead>
            <tbody>{rows}</tbody>
            </table>
        </div>"""

        if not links:
            body += '<p style="color:#94a3b8;text-align:center;padding:32px">No links found.</p>'

        return HTMLResponse(_page("Links", body))
    except Exception as e:
        return HTMLResponse(_page("Error", f'<div class="msg-err">Error: {_esc(str(e))}</div>'))


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

        # Get current link details
        current_link = None
        current_link_id = gs.get("current_link_id")
        if current_link_id:
            cl_resp = supabase.table("links").select("id, title, url").eq("id", current_link_id).execute()
            current_link = cl_resp.data[0] if cl_resp.data else None

        # Time remaining
        now = datetime.now(timezone.utc)
        time_remaining = "-"
        rotation_ends = gs.get("rotation_ends_at")
        if rotation_ends:
            try:
                ends_at = datetime.fromisoformat(rotation_ends.replace("Z", "+00:00"))
                secs = max(0, int((ends_at - now).total_seconds()))
                time_remaining = f"{secs // 60}m {secs % 60}s" if secs > 0 else "Expired"
            except Exception:
                time_remaining = "?"

        # Satellites
        satellites = gs.get("satellites") or []
        sat_html = ""
        if satellites:
            for s in satellites:
                revealed = "Yes" if s.get("revealed") else "No"
                sat_title = _esc(s.get("title", "?")[:40])
                sat_html += f'<div class="log-entry">[{_esc(s.get("position","?"))}] {sat_title} &mdash; revealed: {revealed}</div>'
        else:
            sat_html = '<span style="color:#94a3b8">None</span>'

        # Recent log
        log_resp = supabase.table("director_log").select("*").order("selected_at", desc=True).limit(8).execute()
        log_entries = log_resp.data or []
        log_html = ""
        for entry in log_entries:
            ts = (entry.get("selected_at") or "")[:19]
            reason = _esc(entry.get("reason", "?"))
            eid = entry.get("link_id", "?")
            dur = entry.get("duration_seconds", "?")
            log_html += f'<div class="log-entry">{ts} &mdash; link #{eid}, pool: {reason}, dur: {dur}s</div>'
        if not log_html:
            log_html = '<span style="color:#94a3b8">No entries yet</span>'

        # Score weights
        weights_resp = supabase.table("score_weights").select("*").execute()
        weights = weights_resp.data or []
        weights_html = ""
        for w in weights:
            wkey = _esc(w.get("key", "?"))
            wval = w.get("value", 0)
            weights_html += f"""<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid #f1f5f9">
                <span style="flex:1;font-size:13px;font-family:monospace">{wkey}</span>
                <form method="POST" action="/api/weights/{wkey}" style="display:flex;gap:4px;align-items:center">
                    <input type="number" name="value" value="{wval}" step="any" style="width:80px">
                    <button class="btn-sm">Save</button>
                </form>
            </div>"""

        # --- Director card ---
        status_cls = "status-running" if director.running else "status-stopped"
        status_text = "[RUNNING]" if director.running else "[STOPPED]"

        current_info = "None"
        if current_link:
            ct = _esc(current_link.get("title", "?")[:60])
            cu = _esc(current_link.get("url", "")[:80])
            current_info = f'<strong>{ct}</strong><br><a href="{_esc(current_link.get("url",""))}" target="_blank" style="font-size:12px">{cu}</a>'

        director_html = f"""<div class="card">
            <h2>Director</h2>
            <div class="kv"><span class="label">Status</span><span class="{status_cls}">{status_text}</span></div>
            <div class="kv"><span class="label">Current Link</span><span>{current_info}</span></div>
            <div class="kv"><span class="label">Selection Reason</span><span>{_esc(gs.get("selection_reason", "-"))}</span></div>
            <div class="kv"><span class="label">Time Remaining</span><span>{time_remaining}</span></div>
            <div class="kv"><span class="label">Started At</span><span>{_esc((gs.get("started_at") or "-")[:19])}</span></div>
            <div class="kv"><span class="label">Rotation Ends</span><span>{_esc((rotation_ends or "-")[:19])}</span></div>
            <div class="kv"><span class="label">Viewers</span><span>{len(connected_clients)}</span></div>
            <div style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap">
                <form method="POST" action="/admin/director/start" class="inline-form"><button class="btn btn-primary btn-sm">&#9654; Start</button></form>
                <form method="POST" action="/admin/director/stop" class="inline-form"><button class="btn btn-sm">&#9632; Stop</button></form>
                <form method="POST" action="/admin/director/skip" class="inline-form"><button class="btn btn-sm">&#9193; Skip</button></form>
                <form method="POST" action="/admin/propagate" class="inline-form"><button class="btn btn-sm">Propagate Scores</button></form>
            </div>
            <div style="margin-top:16px">
                <strong style="font-size:13px;color:#475569">Satellites ({len(satellites)})</strong>
                <div style="margin-top:4px">{sat_html}</div>
            </div>
            <div style="margin-top:16px">
                <strong style="font-size:13px;color:#475569">Recent Log</strong>
                <div style="margin-top:4px">{log_html}</div>
            </div>
        </div>"""

        # --- Feeds card ---
        feeds_html = f"""<div class="card">
            <h2>Feeds ({len(feeds)})</h2>
            <form method="POST" action="/admin/add-feed" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px">
                <input type="url" name="url" placeholder="Feed URL" required style="flex:1;min-width:200px">
                <select name="type">
                    <option value="youtube">YouTube</option>
                    <option value="rss">RSS</option>
                    <option value="reddit">Reddit</option>
                    <option value="bluesky">Bluesky</option>
                    <option value="website">Website</option>
                </select>
                <button class="btn btn-primary btn-sm">Add Feed</button>
            </form>
            <div style="margin-bottom:12px">
                <form method="POST" action="/admin/sync" class="inline-form"><button class="btn btn-sm">Sync All</button></form>
                <form method="POST" action="/admin/cancel-all" class="inline-form"><button class="btn btn-sm btn-danger">Cancel All</button></form>
            </div>"""

        for f in feeds:
            fid = f["id"]
            furl = _esc(f.get("url", "?"))
            ftype = _esc(f.get("type", "?"))
            fstatus = _esc(f.get("status", "idle"))
            fcount = f.get("link_count", 0) or 0
            ftrust = f.get("trust_score", 1.0) or 1.0
            ferror = f.get("last_error")
            flast = (f.get("last_scraped_at") or "-")[:19]

            # Feed tags
            ft = supabase.table("feed_tags").select("tag_id").eq("feed_id", fid).execute()
            tag_ids = [t["tag_id"] for t in (ft.data or [])]
            feed_tag_names = []
            if tag_ids:
                tags = supabase.table("tags").select("name,slug").in_("id", tag_ids).execute()
                feed_tag_names = tags.data or []

            tags_html = " ".join(
                f'<span class="tag">{_esc(t["name"])}'
                f'<a href="/admin/feeds/{fid}/tags/{_esc(t["slug"])}/delete" class="del">&times;</a></span>'
                for t in feed_tag_names
            )

            status_color = "#16a34a" if fstatus == "idle" else ("#f59e0b" if fstatus == "syncing" else "#dc2626")
            error_line = f'<div style="color:#dc2626;font-size:12px;margin-top:4px">Error: {_esc(ferror[:100])}</div>' if ferror else ""

            feeds_html += f"""<div class="feed-box">
                <div style="display:flex;justify-content:space-between;align-items:start;flex-wrap:wrap;gap:6px">
                    <div>
                        <strong>[{ftype}]</strong> {furl}
                        <div style="font-size:12px;color:#64748b;margin-top:2px">
                            Status: <span style="color:{status_color};font-weight:600">{fstatus}</span>
                            &middot; Links: <a href="/links?feed_id={fid}">{fcount}</a>
                            &middot; Trust: {ftrust:.2f}
                            &middot; Last sync: {_esc(flast)}
                        </div>
                        {error_line}
                        <div style="margin-top:4px">{tags_html}
                            <form method="POST" action="/admin/feeds/{fid}/tags" style="display:inline-flex;gap:4px;align-items:center">
                                <input type="text" name="tag" placeholder="tag" style="width:80px">
                                <button class="btn-sm">+</button>
                            </form>
                        </div>
                    </div>
                    <div style="display:flex;gap:4px">
                        <form method="POST" action="/admin/sync-feed/{fid}" class="inline-form"><button class="btn-sm">Sync</button></form>
                        <form method="POST" action="/admin/delete-feed/{fid}" class="inline-form"
                              onsubmit="return confirm('Delete this feed and all its links?')">
                            <button class="btn-sm btn-danger">Delete</button>
                        </form>
                    </div>
                </div>
            </div>"""

        feeds_html += "</div>"

        # --- Weights card ---
        weights_card = f"""<div class="card">
            <h2>Score Weights</h2>
            {weights_html if weights_html else '<span style="color:#94a3b8">No weights configured</span>'}
        </div>"""

        # --- Assemble ---
        body = _messages(message, error)
        body += director_html
        body += '<div class="grid-2">'
        body += feeds_html
        body += weights_card
        body += '</div>'

        return HTMLResponse(_page("Admin", body))
    except Exception as e:
        return HTMLResponse(_page("Error", f'<div class="msg-err">Error: {_esc(str(e))}</div>'))


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


# ============================================================
# Sync Engine (unchanged)
# ============================================================

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


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('PORT', 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
