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
from fastapi import FastAPI, BackgroundTasks, Form, Request, Response, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from db_compat import CompatClient
from pydantic import BaseModel

from ingest import (
    parse_youtube_channel, parse_rss_feed, parse_reddit_feed,
    parse_bluesky_feed, scrape_article, vectorize
)
from director import Director
from gatherer import RSSGatherer, GatherScheduler
from worker import start_background_worker, stop_background_worker, get_worker_status, run_processing_batch, is_worker_running
from scratchpad_routes import register_scratchpad_routes
from user_utils import generate_display_name

import ingest as ingest_module
from scratchpad_api import router as scratchpad_router, init as scratchpad_init, normalize_url, get_reddit_api_status
from ai_routes import create_ai_router

load_dotenv()

supabase = CompatClient()  # Direct postgres via psycopg2

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

# ============================================================
# RSS Gatherer Setup
# ============================================================

gatherer = RSSGatherer(supabase, broadcast_fn=broadcast_event)
gather_scheduler = GatherScheduler(gatherer, interval_hours=4.0)


# --- Lifespan (Director + Gatherer startup/shutdown) ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-start the director, gather scheduler, and background worker
    director.start()
    gather_scheduler.start()
    start_background_worker(interval_seconds=90)  # Run processing batch every 90 seconds
    print("[App] Ready. Director, GatherScheduler, and Worker auto-started.")
    yield
    director.stop()
    gather_scheduler.stop()
    stop_background_worker()
    await gatherer.close()


app = FastAPI(title="Linksite", lifespan=lifespan)

# ============================================================
# Admin Authentication (HTTP Basic Auth)
# ============================================================

security = HTTPBasic()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials. Username can be anything, password must match ADMIN_PASSWORD."""
    if not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_PASSWORD not configured on server"
        )
    password_correct = secrets.compare_digest(credentials.password.encode("utf8"), ADMIN_PASSWORD.encode("utf8"))
    if not password_correct:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount scratchpad API
scratchpad_init(supabase, ingest_module)
app.include_router(scratchpad_router)



# Register scratchpad API + HTML routes
register_scratchpad_routes(app, supabase, vectorize)

# AI Content Engine
ai_router = create_ai_router(supabase)
app.include_router(ai_router)

# --- User Identity Middleware ---

@app.middleware("http")
async def user_identity_middleware(request: Request, call_next):
    user_id = request.cookies.get("user_id")
    display_name = None
    new_user = False

    if not user_id:
        user_id = str(uuid.uuid4())
        display_name = generate_display_name()
        new_user = True
        try:
            supabase.table("users").insert({
                "id": user_id,
                "display_name": display_name,
            }).execute()
        except Exception:
            pass  # May already exist
    else:
        # Verify user exists, fetch display_name
        try:
            resp = supabase.table("users").select("display_name").eq("id", user_id).execute()
            if resp.data:
                display_name = resp.data[0].get("display_name", "Anonymous")
            else:
                # Cookie references a deleted user â€” recreate
                display_name = generate_display_name()
                new_user = True
                try:
                    supabase.table("users").insert({
                        "id": user_id,
                        "display_name": display_name,
                    }).execute()
                except Exception:
                    pass
        except Exception:
            display_name = "Anonymous"

    request.state.user_id = user_id
    request.state.display_name = display_name or "Anonymous"
    response = await call_next(request)

    # Set cookie if new user
    if new_user:
        response.set_cookie(
            key="user_id",
            value=user_id,
            httponly=False,  # Allow JS to read for localStorage sync
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
# User API Endpoints
# ============================================================

@app.post("/api/user")
async def api_create_user():
    """Create a new anonymous user with a fun display name."""
    user_id = str(uuid.uuid4())
    display_name = generate_display_name()
    try:
        resp = supabase.table("users").insert({
            "id": user_id,
            "display_name": display_name,
        }).execute()
        user = resp.data[0] if resp.data else {"id": user_id, "display_name": display_name}
    except Exception as e:
        raise HTTPException(500, f"Failed to create user: {e}")
    return {"user": user}


@app.get("/api/user/{user_id}")
async def api_get_user(user_id: str):
    """Get a user by ID. Used to verify a stored user still exists."""
    resp = supabase.table("users").select("id, display_name, created_at, claimed").eq("id", user_id).execute()
    if not resp.data:
        raise HTTPException(404, "User not found")
    return {"user": resp.data[0]}


@app.get("/api/me")
async def api_get_me(request: Request):
    """Get the current user from the cookie/session."""
    user_id = request.state.user_id
    display_name = request.state.display_name
    return {
        "user_id": user_id,
        "display_name": display_name,
    }


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
        <a href="/browse">Browse</a>
        <a href="/add">+ Add</a>
        <a href="/admin">Admin</a>
        <a href="/admin/links">Links</a>
        <a href="/admin/ai">AI Engine</a>
        <a href="/admin/api-status">API Status</a>
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



@app.get("/api/stream-test")
async def test_stream():
    """Minimal SSE test endpoint."""
    async def gen():
        import json, time as _t
        for i in range(10):
            payload = {"type": "state", "test": True, "i": i, "time": _t.time()}
            yield f"event: state\ndata: {json.dumps(payload)}\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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
                    event_type = event.get("type", "action")
                    yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat: send full state
                    try:
                        state = await get_stream_state()
                        yield f"event: state\ndata: {json.dumps(state)}\n\n"
                    except Exception as e:
                        print(f"[SSE] Error in get_stream_state: {e}")
                        import traceback
                        traceback.print_exc()
                        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                except Exception as e:
                    print(f"[SSE] Error in event handler: {e}")
                    import traceback
                    traceback.print_exc()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[SSE] Generator crashed: {e}")
            import traceback
            traceback.print_exc()
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
async def admin_director_start(admin: str = Depends(verify_admin)):
    director.start()
    return RedirectResponse(url="/admin?message=Director started", status_code=303)


@app.post("/admin/director/stop")
async def admin_director_stop(admin: str = Depends(verify_admin)):
    director.stop()
    return RedirectResponse(url="/admin?message=Director stopped", status_code=303)


@app.post("/admin/director/skip")
async def admin_director_skip(admin: str = Depends(verify_admin)):
    director.skip()
    return RedirectResponse(url="/admin?message=Skip requested", status_code=303)


@app.post("/admin/propagate")
async def admin_propagate(admin: str = Depends(verify_admin)):
    director._propagate_scores()
    return RedirectResponse(url="/admin?message=Scores propagated", status_code=303)


@app.get("/admin/director/status")
async def admin_director_status(admin: str = Depends(verify_admin)):
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
# Admin: Background Worker Controls
# ============================================================

@app.get("/api/admin/worker/status")
async def admin_worker_status(admin: str = Depends(verify_admin)):
    """Get current worker status: queue size, monthly spend, backoff states."""
    status = get_worker_status()
    status["worker_running"] = is_worker_running()
    return status


@app.post("/api/admin/worker/run")
async def admin_worker_run(
    batch_size: int = 10,
    admin: str = Depends(verify_admin)
):
    """Manually trigger a processing batch (waits for completion, respects lock)."""
    from worker import _get_batch_lock
    lock = _get_batch_lock()
    
    if lock.locked():
        return {"status": "busy", "message": "A batch is already running, please wait"}
    
    async with lock:
        result = await run_processing_batch(batch_size=batch_size)
        print(f"[Admin] Worker batch complete: {result}")
    
    return {"status": "completed", "batch_size": batch_size, "result": result}


@app.post("/api/admin/worker/start")
async def admin_worker_start(admin: str = Depends(verify_admin)):
    """Start the background worker if not running."""
    if is_worker_running():
        return {"status": "already_running"}
    start_background_worker(interval_seconds=90)
    return {"status": "started"}


@app.post("/api/admin/worker/stop")
async def admin_worker_stop(admin: str = Depends(verify_admin)):
    """Stop the background worker."""
    stop_background_worker()
    return {"status": "stopped"}


# ============================================================
# Admin: RSS Gatherer Controls
# ============================================================

@app.post("/api/admin/gather/hn")
async def admin_gather_hn(background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    """Manually trigger HN RSS gathering."""
    async def do_gather():
        result = await gatherer.gather_hn()
        print(f"[Admin] HN gather complete: {result}")

    background_tasks.add_task(do_gather)
    return {"status": "started", "source": "hn", "message": "HN gathering started in background"}


@app.post("/api/admin/gather/reddit")
async def admin_gather_reddit(background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    """Manually trigger Reddit RSS gathering."""
    async def do_gather():
        result = await gatherer.gather_reddit()
        print(f"[Admin] Reddit gather complete: {result}")

    background_tasks.add_task(do_gather)
    return {"status": "started", "source": "reddit", "message": "Reddit gathering started in background"}


@app.post("/api/admin/gather/all")
async def admin_gather_all(background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    """Manually trigger gathering from all sources (HN + Reddit)."""
    async def do_gather():
        result = await gatherer.gather_all()
        print(f"[Admin] Full gather complete: {result}")

    background_tasks.add_task(do_gather)
    return {"status": "started", "source": "all", "message": "Full gathering started in background"}


@app.get("/api/admin/gather/status")
async def admin_gather_status(admin: str = Depends(verify_admin)):
    """Get gatherer status, scheduler info, and recent job runs."""
    # Get scheduler status with next gather ETA
    scheduler_status = gather_scheduler.get_status()
    
    # Get recent job runs
    try:
        recent_runs = supabase.table("job_runs").select("*").eq(
            "job_type", "gather"
        ).order("created_at", desc=True).limit(10).execute()
    except Exception:
        recent_runs = type('obj', (object,), {'data': []})()

    return {
        "scheduler_running": scheduler_status["running"],
        "interval_hours": scheduler_status["interval_hours"],
        "next_gather_time": scheduler_status["next_gather_time"],
        "seconds_until_next": scheduler_status["seconds_until_next"],
        "last_gather_ago_sec": scheduler_status["last_gather_ago_sec"],
        "recent_runs": recent_runs.data or [],
    }


@app.get("/api/admin/job-runs")
async def admin_job_runs(
    limit: int = 20,
    job_type: Optional[str] = None,
    admin: str = Depends(verify_admin)
):
    """Get recent job runs with optional filtering. Includes link details for expandable view."""
    try:
        query = supabase.table("job_runs").select("*").order("started_at", desc=True).limit(limit)
        if job_type:
            query = query.eq("job_type", job_type)
        result = query.execute()
        runs = result.data or []
        
        # Enrich runs with link titles for processed links
        for run in runs:
            # Calculate duration from started_at and completed_at
            if run.get("started_at") and run.get("completed_at"):
                try:
                    start = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(run["completed_at"].replace("Z", "+00:00"))
                    run["duration_seconds"] = round((end - start).total_seconds(), 1)
                except Exception:
                    run["duration_seconds"] = None
            else:
                run["duration_seconds"] = None
            
            # Get link details for links_processed
            links_processed = run.get("links_processed") or []
            if links_processed and isinstance(links_processed, list) and len(links_processed) > 0:
                try:
                    links_resp = supabase.table("links").select("id, title, url").in_("id", links_processed).execute()
                    run["links_details"] = links_resp.data or []
                except Exception:
                    run["links_details"] = []
            else:
                run["links_details"] = []
        
        # Get scheduler status for next gather ETA
        scheduler_status = gather_scheduler.get_status()
        
        return {
            "runs": runs,
            "scheduler": scheduler_status,
        }
    except Exception as e:
        return {"error": str(e), "runs": [], "scheduler": None}


# ============================================================
# Admin: Feed Tag Management
# ============================================================

@app.post("/admin/feeds/{feed_id}/tags")
async def admin_add_feed_tag(feed_id: int, tag: str = Form(...), admin: str = Depends(verify_admin)):
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
async def admin_remove_feed_tag(feed_id: int, slug: str, admin: str = Depends(verify_admin)):
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
    return RedirectResponse(url="/add")


@app.get("/admin/links", response_class=HTMLResponse)
async def view_links(message: Optional[str] = None, feed_id: Optional[int] = None, admin: str = Depends(verify_admin)):
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
        filter_html += f'<a href="/admin/links" class="{active_all}">All</a>'
        for f in feeds:
            active_cls = ' active' if feed_id == f["id"] else ''
            fname = feed_map[f["id"]]["name"]
            filter_html += f'<a href="/admin/links?feed_id={f["id"]}" class="{active_cls}">{_esc(fname)}</a>'
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
                    <form method="POST" action="/admin/links/delete/{lid}" class="inline-form"
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


@app.post("/admin/links/delete/{link_id}")
async def delete_link(link_id: int, admin: str = Depends(verify_admin)):
    supabase.table('links').delete().eq('id', link_id).execute()
    return RedirectResponse(url="/admin/links?message=Deleted", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(message: Optional[str] = None, error: Optional[str] = None, admin: str = Depends(verify_admin)):
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
                            &middot; Links: <a href="/admin/links?feed_id={fid}">{fcount}</a>
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


        # --- Reddit API Status ---
        try:
            reddit_status = get_reddit_api_status()
            r_configured = reddit_status.get("configured", False)
            r_token_valid = reddit_status.get("token_valid", False)
            r_total_calls = reddit_status.get("total_calls", 0)
            r_searches = reddit_status.get("searches", 0)
            r_resolves = reddit_status.get("resolves", 0)
            r_refreshes = reddit_status.get("token_refreshes", 0)
            r_last_error = _esc(reddit_status.get("last_error") or "None")
            r_avg_rpm = reddit_status.get("avg_rpm", 0)
            r_token_exp = reddit_status.get("token_expires_in_sec", 0)
            r_uptime = reddit_status.get("uptime_sec", 0)
            r_last_search = reddit_status.get("last_search_time")

            r_status_color = "#16a34a" if r_token_valid else ("#f59e0b" if r_configured else "#dc2626")
            r_status_text = "Authenticated" if r_token_valid else ("Configured (no token)" if r_configured else "Not Configured")

            r_last_search_str = "-"
            if r_last_search:
                import time as _admin_time
                ago = _admin_time.time() - r_last_search
                if ago < 60:
                    r_last_search_str = f"{int(ago)}s ago"
                elif ago < 3600:
                    r_last_search_str = f"{int(ago//60)}m ago"
                else:
                    r_last_search_str = f"{int(ago//3600)}h ago"

            r_uptime_str = f"{r_uptime // 3600}h {(r_uptime % 3600) // 60}m"

            reddit_html = f"""<div class="card">
                <h2>&#129302; Reddit API</h2>
                <div class="kv"><span class="label">Status</span><span style="color:{r_status_color};font-weight:700">{r_status_text}</span></div>
                <div class="kv"><span class="label">Token Expires</span><span>{r_token_exp // 3600}h {(r_token_exp % 3600) // 60}m</span></div>
                <div class="kv"><span class="label">Total API Calls</span><span>{r_total_calls}</span></div>
                <div class="kv"><span class="label">Searches / Resolves</span><span>{r_searches} / {r_resolves}</span></div>
                <div class="kv"><span class="label">Token Refreshes</span><span>{r_refreshes}</span></div>
                <div class="kv"><span class="label">Avg RPM</span><span>{r_avg_rpm:.1f}</span></div>
                <div class="kv"><span class="label">Last Search</span><span>{r_last_search_str}</span></div>
                <div class="kv"><span class="label">Last Error</span><span style="font-size:12px;color:{'#dc2626' if r_last_error != 'None' else '#94a3b8'}">{r_last_error}</span></div>
                <div class="kv"><span class="label">Uptime</span><span>{r_uptime_str}</span></div>
            </div>"""
        except Exception as e:
            reddit_html = f'<div class="card"><h2>&#129302; Reddit API</h2><div class="msg-err">Error loading status: {_esc(str(e))}</div></div>'


        # --- Processing Queue Status ---
        try:
            # Count links by processing status (using direct count if available)
            new_links = supabase.table("links").select("id").eq("processing_status", "new").execute()
            processing_links = supabase.table("links").select("id").eq("processing_status", "processing").execute()
            
            # Priority breakdown
            user_submitted = supabase.table("links").select("id").eq("source", "scratchpad").eq("processing_status", "new").execute()
            
            new_count = len(new_links.data or [])
            processing_count = len(processing_links.data or [])
            user_count = len(user_submitted.data or [])
            rss_count = new_count - user_count
            
            queue_html = f"""<div class="card">
                <h2>&#128203; Processing Queue</h2>
                <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:12px">
                    <div style="background:#f0fdf4;padding:12px;border-radius:8px;text-align:center">
                        <div style="font-size:24px;font-weight:700;color:#166534">{new_count}</div>
                        <div style="font-size:12px;color:#64748b">Pending</div>
                    </div>
                    <div style="background:#fef3c7;padding:12px;border-radius:8px;text-align:center">
                        <div style="font-size:24px;font-weight:700;color:#92400e">{processing_count}</div>
                        <div style="font-size:12px;color:#64748b">Processing</div>
                    </div>
                </div>
                <div class="kv"><span class="label">User Submitted</span><span style="font-weight:600;color:#2563eb">{user_count}</span></div>
                <div class="kv"><span class="label">RSS/Feed Links</span><span>{rss_count}</span></div>
            </div>"""
        except Exception as e:
            queue_html = f'<div class="card"><h2>&#128203; Processing Queue</h2><div class="msg-err">Error: {_esc(str(e))}</div></div>'

        # --- API Health / Backoff Status ---
        try:
            from backoff import get_backoff_status
            apis = ["anthropic", "reddit", "hackernews"]
            api_rows = ""
            
            for api_name in apis:
                status = get_backoff_status(api_name)
                is_backing_off = status.get("is_backing_off", False)
                failures = status.get("consecutive_failures", 0)
                backoff_until = status.get("backoff_until")
                last_error = status.get("last_error")
                
                status_color = "#dc2626" if is_backing_off else ("#f59e0b" if failures > 0 else "#16a34a")
                status_text = "Backed off" if is_backing_off else ("Warning" if failures > 0 else "OK")
                status_icon = "&#128308;" if is_backing_off else ("&#128992;" if failures > 0 else "&#128994;")
                
                backoff_info = ""
                if is_backing_off and backoff_until:
                    backoff_info = f'<br><span style="font-size:11px;color:#64748b">until {_esc(backoff_until[:19])}</span>'
                
                error_info = ""
                if last_error:
                    error_info = f'<br><span style="font-size:11px;color:#dc2626">{_esc(last_error[:50])}...</span>'
                
                api_rows += f"""<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f1f5f9">
                    <div>
                        <strong style="font-size:14px">{api_name.title()}</strong>
                        {error_info}
                    </div>
                    <div style="text-align:right">
                        <span style="color:{status_color};font-weight:600">{status_icon} {status_text}</span>
                        {backoff_info}
                        <br><span style="font-size:11px;color:#64748b">Failures: {failures}</span>
                    </div>
                </div>"""
            
            api_health_html = f"""<div class="card">
                <h2>&#128161; API Health</h2>
                {api_rows}
            </div>"""
        except Exception as e:
            api_health_html = f'<div class="card"><h2>&#128161; API Health</h2><div class="msg-err">Error: {_esc(str(e))}</div></div>'

        # --- Monthly AI Budget ---
        try:
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            usage_resp = supabase.table("ai_token_usage").select("estimated_cost_usd").gte("created_at", month_start.isoformat()).execute()
            
            total_cost = sum(float(r.get("estimated_cost_usd", 0) or 0) for r in (usage_resp.data or []))
            budget = 50.0
            percentage = min((total_cost / budget) * 100, 100)
            warning = total_cost > (budget * 0.8)
            
            bar_color = "#dc2626" if warning else ("#f59e0b" if percentage > 50 else "#16a34a")
            warning_text = '<span style="color:#dc2626;font-weight:600">&#9888; Budget Warning!</span>' if warning else ''
            
            budget_html = f"""<div class="card">
                <h2>&#128176; Monthly AI Budget</h2>
                <div style="font-size:28px;font-weight:700;color:#1e293b;margin-bottom:8px">${total_cost:.2f} <span style="font-size:16px;color:#64748b;font-weight:400">/ ${budget:.2f}</span></div>
                <div style="background:#e2e8f0;border-radius:6px;height:16px;overflow:hidden;margin-bottom:8px">
                    <div style="background:{bar_color};height:100%;width:{percentage:.1f}%;transition:width 0.3s"></div>
                </div>
                <div class="kv"><span class="label">Usage</span><span>{percentage:.1f}%</span></div>
                <div class="kv"><span class="label">Remaining</span><span>${budget - total_cost:.2f}</span></div>
                <div class="kv"><span class="label">Month</span><span>{now.strftime("%B %Y")}</span></div>
                {warning_text}
            </div>"""
        except Exception as e:
            budget_html = f'<div class="card"><h2>&#128176; Monthly AI Budget</h2><div class="msg-err">Error: {_esc(str(e))}</div></div>'

        # --- Recent Job Runs (with live refresh) ---
        try:
            # Get scheduler status for next gather ETA
            scheduler_status = gather_scheduler.get_status()
            next_gather_sec = scheduler_status.get("seconds_until_next", 0)
            next_gather_min = next_gather_sec // 60
            next_gather_hr = next_gather_min // 60
            next_gather_min_rem = next_gather_min % 60
            
            if next_gather_hr > 0:
                next_gather_str = f"{next_gather_hr}h {next_gather_min_rem}m"
            elif next_gather_min > 0:
                next_gather_str = f"{next_gather_min}m"
            else:
                next_gather_str = f"{next_gather_sec}s"
            
            last_gather_sec = scheduler_status.get("last_gather_ago_sec")
            if last_gather_sec:
                last_gather_min = last_gather_sec // 60
                last_gather_hr = last_gather_min // 60
                if last_gather_hr > 0:
                    last_gather_str = f"{last_gather_hr}h ago"
                elif last_gather_min > 0:
                    last_gather_str = f"{last_gather_min}m ago"
                else:
                    last_gather_str = f"{last_gather_sec}s ago"
            else:
                last_gather_str = "Never"
            
            # Try job_runs first
            runs_resp = supabase.table("job_runs").select("*").order("started_at", desc=True).limit(10).execute()
            runs = runs_resp.data or []
            
            # Calculate duration for each run
            for run in runs:
                if run.get("started_at") and run.get("completed_at"):
                    try:
                        start = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                        end = datetime.fromisoformat(run["completed_at"].replace("Z", "+00:00"))
                        run["duration_seconds"] = round((end - start).total_seconds(), 1)
                    except Exception:
                        run["duration_seconds"] = None
                else:
                    run["duration_seconds"] = None
            
            runs_rows = ""
            for idx, run in enumerate(runs[:10]):
                r_id = run.get("id", "")[:8]
                r_type = _esc(run.get("type") or run.get("job_type") or "?")
                r_status = run.get("status", "?")
                r_started = (run.get("started_at") or run.get("created_at") or "")[:19]
                r_duration = run.get("duration_seconds")
                r_items = run.get("items_processed") or 0
                links_processed = run.get("links_processed") or []
                
                status_colors = {"completed": "#16a34a", "failed": "#dc2626", "running": "#f59e0b", "completed_with_errors": "#f59e0b"}
                s_color = status_colors.get(r_status, "#64748b")
                
                dur_str = f"{r_duration}s" if r_duration is not None else "-"
                
                # Check if row is expandable (has links_processed)
                has_details = len(links_processed) > 0 if isinstance(links_processed, list) else False
                expand_icon = "&#9654;" if has_details else ""
                row_class = "job-row expandable" if has_details else "job-row"
                row_id = f"job-row-{idx}"
                
                runs_rows += f"""<tr class="{row_class}" data-job-id="{_esc(r_id)}" id="{row_id}" onclick="toggleJobDetails('{row_id}')" style="cursor:{'pointer' if has_details else 'default'}">
                    <td style="font-weight:500"><span class="expand-icon">{expand_icon}</span> {r_type}</td>
                    <td><span style="color:{s_color};font-weight:600">{_esc(r_status)}</span></td>
                    <td style="font-size:12px;color:#64748b">{r_started}</td>
                    <td style="text-align:center">{dur_str}</td>
                    <td style="text-align:center">{r_items}</td>
                </tr>"""
                
                # Add hidden details row
                if has_details:
                    runs_rows += f"""<tr class="job-details" id="{row_id}-details" style="display:none;background:#f8fafc">
                        <td colspan="5" style="padding:12px 16px">
                            <strong style="font-size:12px;color:#64748b">Links Processed:</strong>
                            <div id="{row_id}-links" style="margin-top:8px;font-size:13px">Loading...</div>
                        </td>
                    </tr>"""
            
            if not runs_rows:
                runs_rows = '<tr><td colspan="5" style="color:#94a3b8;text-align:center;padding:16px">No job runs yet</td></tr>'
            
            jobs_html = f"""<div class="card">
                <h2>&#128203; Recent Job Runs <span id="jobs-refresh-indicator" style="font-size:12px;color:#94a3b8;font-weight:400"></span></h2>
                <div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap">
                    <div style="background:#f0f9ff;padding:8px 12px;border-radius:6px;font-size:13px">
                        <span style="color:#64748b">Next gather:</span> 
                        <span id="next-gather-countdown" style="font-weight:600;color:#1e40af">{next_gather_str}</span>
                    </div>
                    <div style="background:#f0fdf4;padding:8px 12px;border-radius:6px;font-size:13px">
                        <span style="color:#64748b">Last gather:</span> 
                        <span style="font-weight:600;color:#166534">{last_gather_str}</span>
                    </div>
                </div>
                <div style="overflow-x:auto">
                <table id="job-runs-table">
                <thead><tr>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Started</th>
                    <th style="text-align:center">Duration</th>
                    <th style="text-align:center">Items</th>
                </tr></thead>
                <tbody id="job-runs-tbody">{runs_rows}</tbody>
                </table>
                </div>
            </div>
            <style>
            .job-row.expandable:hover {{ background: #f8fafc; }}
            .job-row .expand-icon {{ display: inline-block; width: 16px; transition: transform 0.2s; }}
            .job-row.expanded .expand-icon {{ transform: rotate(90deg); }}
            .job-details {{ border-left: 3px solid #2563eb; }}
            </style>
            <script>
            // Toggle job details expansion
            function toggleJobDetails(rowId) {{
                const row = document.getElementById(rowId);
                const detailsRow = document.getElementById(rowId + '-details');
                if (!detailsRow) return;
                
                const isExpanded = row.classList.contains('expanded');
                if (isExpanded) {{
                    row.classList.remove('expanded');
                    detailsRow.style.display = 'none';
                }} else {{
                    row.classList.add('expanded');
                    detailsRow.style.display = 'table-row';
                    // Load link details if not already loaded
                    const linksDiv = document.getElementById(rowId + '-links');
                    if (linksDiv && linksDiv.textContent === 'Loading...') {{
                        loadJobLinkDetails(rowId);
                    }}
                }}
            }}
            
            // Load link details for a job
            async function loadJobLinkDetails(rowId) {{
                const linksDiv = document.getElementById(rowId + '-links');
                try {{
                    const response = await fetch('/api/admin/job-runs?limit=20');
                    const data = await response.json();
                    // Find the matching job by index (rowId is job-row-N)
                    const idx = parseInt(rowId.replace('job-row-', ''));
                    const job = data.runs[idx];
                    if (job && job.links_details && job.links_details.length > 0) {{
                        linksDiv.innerHTML = job.links_details.map(link => 
                            `<div style="padding:4px 0;border-bottom:1px solid #e2e8f0">
                                <a href="/link/${{link.id}}" target="_blank" style="font-weight:500">#${{link.id}}</a>
                                ${{link.title ? ' — ' + link.title.substring(0, 60) : ''}}
                            </div>`
                        ).join('');
                    }} else {{
                        linksDiv.innerHTML = '<span style="color:#94a3b8">No link details available</span>';
                    }}
                }} catch (e) {{
                    linksDiv.innerHTML = '<span style="color:#dc2626">Error loading details</span>';
                }}
            }}
            
            // Live refresh job runs every 10 seconds
            let refreshInterval;
            async function refreshJobRuns() {{
                const indicator = document.getElementById('jobs-refresh-indicator');
                const tbody = document.getElementById('job-runs-tbody');
                const countdown = document.getElementById('next-gather-countdown');
                
                try {{
                    indicator.textContent = '(refreshing...)';
                    const response = await fetch('/api/admin/job-runs?limit=10');
                    const data = await response.json();
                    
                    if (data.runs && data.runs.length > 0) {{
                        // Update the table with new data (simplified - just show indicator)
                        indicator.textContent = '(auto-refresh active)';
                    }}
                    
                    // Update next gather countdown
                    if (data.scheduler && data.scheduler.seconds_until_next !== undefined) {{
                        const sec = data.scheduler.seconds_until_next;
                        const hr = Math.floor(sec / 3600);
                        const min = Math.floor((sec % 3600) / 60);
                        if (hr > 0) {{
                            countdown.textContent = hr + 'h ' + min + 'm';
                        }} else if (min > 0) {{
                            countdown.textContent = min + 'm';
                        }} else {{
                            countdown.textContent = sec + 's';
                        }}
                    }}
                    
                    setTimeout(() => {{ indicator.textContent = ''; }}, 2000);
                }} catch (e) {{
                    indicator.textContent = '(refresh error)';
                }}
            }}
            
            // Start auto-refresh
            refreshInterval = setInterval(refreshJobRuns, 10000);
            
            // Countdown timer for next gather (updates every second)
            let nextGatherSec = {next_gather_sec};
            setInterval(() => {{
                if (nextGatherSec > 0) {{
                    nextGatherSec--;
                    const countdown = document.getElementById('next-gather-countdown');
                    if (countdown) {{
                        const hr = Math.floor(nextGatherSec / 3600);
                        const min = Math.floor((nextGatherSec % 3600) / 60);
                        const sec = nextGatherSec % 60;
                        if (hr > 0) {{
                            countdown.textContent = hr + 'h ' + min + 'm';
                        }} else if (min > 0) {{
                            countdown.textContent = min + 'm ' + sec + 's';
                        }} else {{
                            countdown.textContent = sec + 's';
                        }}
                    }}
                }}
            }}, 1000);
            </script>"""
        except Exception as e:
            import traceback
            traceback.print_exc()
            jobs_html = f'<div class="card"><h2>&#128203; Recent Job Runs</h2><div class="msg-err">Error: {_esc(str(e))}</div></div>'

        # --- Manual Triggers ---
        triggers_html = """<div class="card">
            <h2>&#9889; Manual Triggers</h2>
            <p style="font-size:13px;color:#64748b;margin-bottom:12px">Run jobs manually (results shown on refresh)</p>
            <div style="display:flex;flex-wrap:wrap;gap:8px">
                <button class="btn btn-sm" onclick="triggerJob('/api/admin/gather/hn', this)">&#129412; Gather HN</button>
                <button class="btn btn-sm" onclick="triggerJob('/api/admin/gather/reddit', this)">&#129302; Gather Reddit</button>
                <button class="btn btn-sm btn-primary" onclick="triggerJob('/api/admin/worker/run', this)">&#10024; Run Processing</button>
            </div>
            <div id="trigger-result" style="margin-top:12px;font-size:13px;color:#64748b"></div>
        </div>
        <script>
        function triggerJob(url, btn) {
            btn.disabled = true;
            btn.textContent = 'Running...';
            fetch(url, {method: 'POST'})
                .then(r => r.json())
                .then(d => {
                    document.getElementById('trigger-result').innerHTML = 
                        '<span style="color:#16a34a">&#10003; ' + (d.message || 'Job started') + '</span>';
                    btn.disabled = false;
                    btn.textContent = btn.textContent.replace('Running...', '');
                    location.reload();
                })
                .catch(e => {
                    document.getElementById('trigger-result').innerHTML = 
                        '<span style="color:#dc2626">&#10007; Error: ' + e.message + '</span>';
                    btn.disabled = false;
                });
        }
        </script>"""

        # --- Assemble ---
        body = _messages(message, error)
        body += director_html
        body += '<div class="grid-2">'
        body += feeds_html
        body += weights_card
        body += '</div>'
        body += '<div class="grid-2">'
        body += queue_html
        body += budget_html
        body += '</div>'
        body += '<div class="grid-2">'
        body += api_health_html
        body += triggers_html
        body += '</div>'
        body += jobs_html
        body += reddit_html

        return HTMLResponse(_page("Admin", body))
    except Exception as e:
        return HTMLResponse(_page("Error", f'<div class="msg-err">Error: {_esc(str(e))}</div>'))


@app.get("/admin/api-status", response_class=HTMLResponse)
async def admin_api_status(request: Request, admin: str = Depends(verify_admin)):
    """HTML page showing current API status (same data as /api/now but in HTML format)."""
    try:
        user_id = request.state.user_id
        now = datetime.now(timezone.utc)

        state = supabase.table("global_state").select("*").eq("id", 1).execute()
        gs = state.data[0] if state.data else {}

        if not gs.get("current_link_id"):
            body = '<div class="msg-err">Director not running or no link selected</div>'
            return HTMLResponse(_page("API Status", body))

        link_id = gs["current_link_id"]

        # Get current link
        link_resp = supabase.table("links").select(
            "id, url, title, meta_json, direct_score, feed_id"
        ).eq("id", link_id).execute()
        link = link_resp.data[0] if link_resp.data else None

        # Get tags via feed_tags
        tags = []
        if link and link.get("feed_id"):
            ft_resp = supabase.table("feed_tags").select("tag_id").eq("feed_id", link["feed_id"]).execute()
            tag_ids = [ft["tag_id"] for ft in (ft_resp.data or [])]
            if tag_ids:
                tags_resp = supabase.table("tags").select("name, slug").in_("id", tag_ids).execute()
                tags = tags_resp.data or []

        # Satellites
        satellites = gs.get("satellites") or []
        rotation_id = gs.get("started_at", "")
        for sat in satellites:
            reveal_at = sat.get("reveal_at")
            if reveal_at:
                sat["revealed"] = now >= datetime.fromisoformat(reveal_at.replace("Z", "+00:00"))
            else:
                sat["revealed"] = True

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

        # Build HTML
        link_html = f"""<div class="card">
            <h2>&#127775; Current Featured Link</h2>
            <div class="kv"><span class="label">ID</span><span>{link.get("id", "?") if link else "-"}</span></div>
            <div class="kv"><span class="label">Title</span><span>{_esc(link.get("title", "?")[:80]) if link else "-"}</span></div>
            <div class="kv"><span class="label">URL</span><span><a href="{_esc(link.get("url", ""))}" target="_blank">{_esc((link.get("url", ""))[:60])}</a></span></div>
            <div class="kv"><span class="label">Direct Score</span><span>{link.get("direct_score", 0) if link else 0}</span></div>
            <div class="kv"><span class="label">Feed ID</span><span>{link.get("feed_id", "-") if link else "-"}</span></div>
        </div>"""

        tags_html = " ".join(f'<span class="tag">{_esc(t["name"])}</span>' for t in tags) or '<span style="color:#94a3b8">None</span>'
        tags_card = f"""<div class="card">
            <h2>&#127991; Tags</h2>
            {tags_html}
        </div>"""

        timer_html = f"""<div class="card">
            <h2>&#9200; Timers</h2>
            <div class="kv"><span class="label">Started At</span><span>{_esc((gs.get("started_at") or "-")[:19])}</span></div>
            <div class="kv"><span class="label">Reveal Ends At</span><span>{_esc((gs.get("reveal_ends_at") or "-")[:19])}</span></div>
            <div class="kv"><span class="label">Rotation Ends At</span><span>{_esc((rotation_ends or "-")[:19])}</span></div>
            <div class="kv"><span class="label">Seconds Remaining</span><span style="font-weight:700;color:#2563eb">{seconds_remaining}</span></div>
        </div>"""

        votes_html = f"""<div class="card">
            <h2>&#128077; Votes</h2>
            <div class="kv"><span class="label">Total Score</span><span style="font-weight:700">{score}</span></div>
            <div class="kv"><span class="label">My Votes Count</span><span>{len(my_votes.data or [])}</span></div>
            <div class="kv"><span class="label">My Last Vote</span><span>{(my_votes.data[0]["created_at"][:19] if my_votes.data else "-")}</span></div>
        </div>"""

        sat_rows = ""
        for s in satellites:
            revealed_icon = "&#10003;" if s.get("revealed") else "&#10007;"
            revealed_color = "#16a34a" if s.get("revealed") else "#dc2626"
            sat_rows += f"""<tr>
                <td>{s.get("link_id", "?")}</td>
                <td>{_esc(s.get("title", "?")[:40])}</td>
                <td>{_esc(s.get("position", "?"))}</td>
                <td><span style="color:{revealed_color}">{revealed_icon}</span></td>
                <td>{s.get("nominations", 0)}</td>
            </tr>"""
        if not sat_rows:
            sat_rows = '<tr><td colspan="5" style="color:#94a3b8;text-align:center">No satellites</td></tr>'

        sat_html = f"""<div class="card">
            <h2>&#128752; Satellites ({len(satellites)})</h2>
            <table>
            <thead><tr><th>ID</th><th>Title</th><th>Position</th><th>Revealed</th><th>Nominations</th></tr></thead>
            <tbody>{sat_rows}</tbody>
            </table>
        </div>"""

        meta_html = f"""<div class="card">
            <h2>&#128203; Meta</h2>
            <div class="kv"><span class="label">Selection Reason</span><span>{_esc(gs.get("selection_reason", "-"))}</span></div>
            <div class="kv"><span class="label">Viewer Count</span><span>{len(connected_clients)}</span></div>
            <div class="kv"><span class="label">Server Time</span><span>{now.isoformat()[:19]}</span></div>
        </div>"""

        body = link_html
        body += '<div class="grid-2">'
        body += timer_html + votes_html
        body += '</div>'
        body += '<div class="grid-2">'
        body += tags_card + meta_html
        body += '</div>'
        body += sat_html

        return HTMLResponse(_page("API Status", body))
    except Exception as e:
        return HTMLResponse(_page("Error", f'<div class="msg-err">Error: {_esc(str(e))}</div>'))


@app.post("/admin/add-feed")
async def add_feed(url: str = Form(...), type: str = Form(...), admin: str = Depends(verify_admin)):
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
async def delete_feed(feed_id: int, admin: str = Depends(verify_admin)):
    supabase.table('links').delete().eq('feed_id', feed_id).execute()
    supabase.table('feed_tags').delete().eq('feed_id', feed_id).execute()
    supabase.table('feeds').delete().eq('id', feed_id).execute()
    return RedirectResponse(url="/admin?message=Feed deleted", status_code=303)


@app.post("/admin/sync")
async def sync_feeds(background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    _sync_all_cancel.clear()
    background_tasks.add_task(sync_all_feeds)
    return RedirectResponse(url="/admin?message=Sync started", status_code=303)


@app.post("/admin/sync-feed/{feed_id}")
async def sync_single_feed(feed_id: int, background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    background_tasks.add_task(sync_feed_by_id, feed_id)
    return RedirectResponse(url="/admin?message=Syncing...", status_code=303)


@app.post("/admin/cancel-all")
async def cancel_all_syncs(admin: str = Depends(verify_admin)):
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
            url = normalize_url(url)
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
                    'processing_status': 'new',
                    'processing_priority': 1,  # Feed items = low priority
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
# Admin: AI Content Engine
# ============================================================

from ai_engine import AIEngine as _AIEngine

def _get_ai_engine():
    """Get a shared AI engine instance."""
    return _AIEngine(supabase)


@app.get("/admin/ai", response_class=HTMLResponse)
async def admin_ai_dashboard(message: str = None, error: str = None, admin: str = Depends(verify_admin)):
    try:
        engine = _get_ai_engine()

        # --- Health ---
        has_anthropic = bool(engine.api_key)
        has_brave = bool(engine.brave_key)

        health_color = "#16a34a" if has_anthropic else "#dc2626"
        health_text = "Operational" if has_anthropic else "Degraded — No API Key"
        brave_color = "#16a34a" if has_brave else "#f59e0b"
        brave_text = "Configured" if has_brave else "Missing (HN fallback)"

        health_html = f"""<div class="card">
            <h2>&#129302; AI Engine Health</h2>
            <div class="kv"><span class="label">Status</span>
                <span style="color:{health_color};font-weight:700">{health_text}</span></div>
            <div class="kv"><span class="label">Anthropic API</span>
                <span style="color:{health_color}">{("&#10003; " if has_anthropic else "&#10007; ")}{"Key set" if has_anthropic else "Not configured"}</span></div>
            <div class="kv"><span class="label">Brave Search</span>
                <span style="color:{brave_color}">{("&#10003; " if has_brave else "&#9888; ")}{brave_text}</span></div>
        </div>"""

        # --- Token Usage Stats ---
        all_runs = supabase.table("ai_runs").select(
            "type, status, results_count, tokens_used, model, created_at"
        ).order("created_at", desc=True).execute()
        runs_data = all_runs.data or []

        now = datetime.now(timezone.utc)
        day_ago = (now - timedelta(hours=24)).isoformat()
        week_ago = (now - timedelta(days=7)).isoformat()

        completed_runs = [r for r in runs_data if r.get("status") == "completed"]
        total_tokens_all = sum(r.get("tokens_used", 0) or 0 for r in completed_runs)
        total_tokens_24h = sum(r.get("tokens_used", 0) or 0 for r in completed_runs
                               if (r.get("created_at") or "") >= day_ago)
        total_tokens_7d = sum(r.get("tokens_used", 0) or 0 for r in completed_runs
                              if (r.get("created_at") or "") >= week_ago)

        # Tokens by model
        tokens_by_model = {}
        for r in completed_runs:
            m = r.get("model") or "unknown"
            tokens_by_model[m] = tokens_by_model.get(m, 0) + (r.get("tokens_used", 0) or 0)

        # Tokens by run type
        tokens_by_type = {}
        for r in completed_runs:
            t = r.get("type") or "unknown"
            tokens_by_type[t] = tokens_by_type.get(t, 0) + (r.get("tokens_used", 0) or 0)

        # Cost estimates (avg input/output ratio ~60/40 for typical usage)
        # Haiku: $0.25/MTok in, $1.25/MTok out -> weighted avg ~$0.65/MTok
        # Sonnet: $3/MTok in, $15/MTok out -> weighted avg ~$7.80/MTok
        cost_rates = {"haiku": 0.65, "sonnet": 7.80, "unknown": 0.65}
        total_cost = 0.0
        cost_by_model = {}
        for model, tok in tokens_by_model.items():
            rate = cost_rates.get(model, 0.65)
            cost = (tok / 1_000_000) * rate
            cost_by_model[model] = cost
            total_cost += cost

        def _fmt_tokens(n):
            if n >= 1_000_000:
                return f"{n/1_000_000:.2f}M"
            elif n >= 1_000:
                return f"{n/1_000:.1f}K"
            return str(n)

        model_rows = ""
        for model in sorted(tokens_by_model.keys()):
            tok = tokens_by_model[model]
            cost = cost_by_model.get(model, 0)
            model_rows += f"""<div class="kv">
                <span class="label">{_esc(model)}</span>
                <span>{_fmt_tokens(tok)} tokens &middot; ~${cost:.4f}</span>
            </div>"""

        type_rows = ""
        for rtype in sorted(tokens_by_type.keys()):
            tok = tokens_by_type[rtype]
            type_rows += f"""<div class="kv">
                <span class="label">{_esc(rtype)}</span>
                <span>{_fmt_tokens(tok)} tokens</span>
            </div>"""

        # Daily breakdown (last 7 days)
        daily_usage = {}
        for r in completed_runs:
            dt = (r.get("created_at") or "")[:10]
            if dt:
                daily_usage[dt] = daily_usage.get(dt, 0) + (r.get("tokens_used", 0) or 0)

        daily_html = ""
        for day in sorted(daily_usage.keys(), reverse=True)[:7]:
            tok = daily_usage[day]
            daily_html += f'<div class="kv"><span class="label">{day}</span><span>{_fmt_tokens(tok)}</span></div>'
        if not daily_html:
            daily_html = '<span style="color:#94a3b8">No usage yet</span>'

        token_html = f"""<div class="card">
            <h2>&#128200; Token Usage</h2>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">
                <div style="background:#f0f9ff;padding:12px;border-radius:8px;text-align:center">
                    <div style="font-size:24px;font-weight:700;color:#1e40af">{_fmt_tokens(total_tokens_all)}</div>
                    <div style="font-size:12px;color:#64748b">All Time</div>
                </div>
                <div style="background:#f0fdf4;padding:12px;border-radius:8px;text-align:center">
                    <div style="font-size:24px;font-weight:700;color:#166534">{_fmt_tokens(total_tokens_24h)}</div>
                    <div style="font-size:12px;color:#64748b">Last 24h</div>
                </div>
                <div style="background:#fefce8;padding:12px;border-radius:8px;text-align:center">
                    <div style="font-size:24px;font-weight:700;color:#854d0e">{_fmt_tokens(total_tokens_7d)}</div>
                    <div style="font-size:12px;color:#64748b">Last 7 Days</div>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
                <div style="background:#faf5ff;padding:12px;border-radius:8px;text-align:center">
                    <div style="font-size:20px;font-weight:700;color:#7c3aed">${total_cost:.4f}</div>
                    <div style="font-size:12px;color:#64748b">Est. Total Cost</div>
                </div>
                <div style="background:#fff1f2;padding:12px;border-radius:8px;text-align:center">
                    <div style="font-size:20px;font-weight:700;color:#be123c">{len(completed_runs)}</div>
                    <div style="font-size:12px;color:#64748b">Completed Runs</div>
                </div>
            </div>
            <details style="margin-top:8px">
                <summary style="cursor:pointer;font-weight:600;font-size:14px;color:#475569">By Model</summary>
                <div style="margin-top:8px">{model_rows if model_rows else '<span style="color:#94a3b8">No data</span>'}</div>
            </details>
            <details style="margin-top:8px">
                <summary style="cursor:pointer;font-weight:600;font-size:14px;color:#475569">By Run Type</summary>
                <div style="margin-top:8px">{type_rows if type_rows else '<span style="color:#94a3b8">No data</span>'}</div>
            </details>
            <details style="margin-top:8px">
                <summary style="cursor:pointer;font-weight:600;font-size:14px;color:#475569">Daily Breakdown</summary>
                <div style="margin-top:8px">{daily_html}</div>
            </details>
        </div>"""

        # --- Discovery Controls ---
        discover_html = f"""<div class="card">
            <h2>&#128269; Discover Links</h2>
            <form method="POST" action="/admin/ai/discover" style="display:flex;flex-direction:column;gap:10px">
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:end">
                    <div style="flex:1;min-width:200px">
                        <label style="font-size:12px;color:#64748b;display:block;margin-bottom:2px">Topic (optional)</label>
                        <input type="text" name="topic" placeholder="e.g. AI safety, Rust programming..." style="width:100%">
                    </div>
                    <div>
                        <label style="font-size:12px;color:#64748b;display:block;margin-bottom:2px">Count</label>
                        <input type="number" name="count" value="5" min="1" max="20" style="width:70px">
                    </div>
                    <div>
                        <label style="font-size:12px;color:#64748b;display:block;margin-bottom:2px">Source</label>
                        <select name="source">
                            <option value="web">Web (Brave)</option>
                            <option value="hn" selected>Hacker News</option>
                            <option value="reddit">Reddit</option>
                        </select>
                    </div>
                    <button class="btn btn-primary" type="submit">&#9889; Discover</button>
                </div>
            </form>
        </div>"""

        # --- Enrichment Controls ---
        enrich_html = f"""<div class="card">
            <h2>&#10024; Enrich Links</h2>
            <form method="POST" action="/admin/ai/enrich" style="display:flex;flex-direction:column;gap:10px">
                <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end">
                    <div>
                        <label style="font-size:12px;color:#64748b;display:block;margin-bottom:2px">Limit</label>
                        <input type="number" name="limit" value="5" min="1" max="50" style="width:70px">
                    </div>
                    <div style="display:flex;gap:12px;align-items:center;padding-top:18px">
                        <label style="font-size:13px"><input type="checkbox" name="types" value="description" checked> Descriptions</label>
                        <label style="font-size:13px"><input type="checkbox" name="types" value="tags" checked> Tags</label>
                        <label style="font-size:13px"><input type="checkbox" name="types" value="comments" checked> Comments</label>
                    </div>
                    <button class="btn btn-primary" type="submit">&#10024; Enrich Batch</button>
                </div>
            </form>
        </div>"""

        # --- Recent Runs ---
        recent_runs = runs_data[:20]
        runs_rows = ""
        for r in recent_runs:
            rid = (r.get("id") or "?")[:8]
            rtype = _esc(r.get("type") or "?")
            rstatus = r.get("status") or "?"
            rtokens = r.get("tokens_used") or 0
            rresults = r.get("results_count") or 0
            rmodel = _esc(r.get("model") or "-")
            rcreated = (r.get("created_at") or "")[:19].replace("T", " ")
            rerror = r.get("error")

            status_color = {"completed": "#16a34a", "failed": "#dc2626", "running": "#f59e0b"}.get(rstatus, "#94a3b8")
            type_badge_bg = {"discover": "#dbeafe", "enrich": "#fce7f3"}.get(rtype, "#f1f5f9")
            type_badge_color = {"discover": "#1e40af", "enrich": "#9d174d"}.get(rtype, "#475569")

            error_html = ""
            if rerror:
                short_err = _esc(rerror[:60])
                error_html = f'<br><span style="color:#dc2626;font-size:11px" title="{_esc(rerror)}">{short_err}...</span>'

            runs_rows += f"""<tr>
                <td><code style="font-size:12px;color:#64748b">{rid}</code></td>
                <td><span style="background:{type_badge_bg};color:{type_badge_color};padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600">{rtype}</span></td>
                <td><span style="color:{status_color};font-weight:600">{_esc(rstatus)}</span>{error_html}</td>
                <td style="text-align:right">{_fmt_tokens(rtokens)}</td>
                <td style="text-align:center">{rresults}</td>
                <td style="font-size:12px;color:#64748b">{rmodel}</td>
                <td style="font-size:12px;color:#64748b">{rcreated}</td>
            </tr>"""

        if not runs_rows:
            runs_rows = '<tr><td colspan="7" style="color:#94a3b8;text-align:center;padding:24px">No runs yet</td></tr>'

        runs_html = f"""<div class="card">
            <h2>&#128203; Recent Runs</h2>
            <div style="overflow-x:auto">
            <table>
            <thead><tr>
                <th>ID</th>
                <th>Type</th>
                <th>Status</th>
                <th style="text-align:right">Tokens</th>
                <th style="text-align:center">Results</th>
                <th>Model</th>
                <th>Created</th>
            </tr></thead>
            <tbody>{runs_rows}</tbody>
            </table>
            </div>
        </div>"""

        # --- Recent AI Content ---
        content_resp = supabase.table("ai_generated_content").select(
            "id, link_id, content_type, content, author, model_used, tokens_used, created_at"
        ).order("created_at", desc=True).limit(20).execute()
        content_items = content_resp.data or []

        content_rows = ""
        for c in content_items:
            clink = c.get("link_id", "?")
            ctype = _esc(c.get("content_type") or "?")
            cauthor = _esc(c.get("author") or "-")
            raw_content = c.get("content") or ""
            preview = _esc(raw_content[:120]) + ("..." if len(raw_content) > 120 else "")
            ccreated = (c.get("created_at") or "")[:19].replace("T", " ")

            type_colors = {
                "description": ("#dbeafe", "#1e40af"),
                "comment": ("#dcfce7", "#166534"),
                "tag": ("#fef3c7", "#92400e"),
                "summary": ("#e0e7ff", "#3730a3"),
                "related": ("#fce7f3", "#9d174d"),
            }
            bg, fg = type_colors.get(ctype, ("#f1f5f9", "#475569"))

            content_rows += f"""<tr>
                <td><a href="/links?feed_id=" style="font-weight:600">#{clink}</a></td>
                <td><span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600">{ctype}</span></td>
                <td style="font-size:12px;color:#64748b">{cauthor}</td>
                <td style="font-size:13px;max-width:400px">{preview}</td>
                <td style="font-size:12px;color:#64748b">{ccreated}</td>
            </tr>"""

        if not content_rows:
            content_rows = '<tr><td colspan="5" style="color:#94a3b8;text-align:center;padding:24px">No AI-generated content yet</td></tr>'

        content_html = f"""<div class="card">
            <h2>&#128172; Recent AI Content</h2>
            <div style="overflow-x:auto">
            <table>
            <thead><tr>
                <th>Link</th>
                <th>Type</th>
                <th>Author</th>
                <th>Preview</th>
                <th>Created</th>
            </tr></thead>
            <tbody>{content_rows}</tbody>
            </table>
            </div>
        </div>"""

        # --- AI Personas Section ---
        try:
            personas = await engine.get_personas()
            persona_rows = ""
            for p in personas:
                pid = _esc(p.get("id", "?"))
                pauthor = _esc(p.get("author", "?"))
                pmodel = _esc(p.get("model", "haiku"))
                pdesc = _esc(p.get("description", "")[:60])
                ppriority = p.get("priority", 50)
                pusage = p.get("usage_count", 0)
                has_custom = "&#10003;" if p.get("has_custom_prompt") else "-"
                
                model_color = "#7c3aed" if pmodel == "sonnet" else "#2563eb"
                
                persona_rows += f"""<tr>
                    <td><strong style="font-size:14px">{pid}</strong></td>
                    <td style="color:#64748b;font-size:13px">{pauthor}</td>
                    <td><span style="background:#f0f9ff;color:{model_color};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600">{pmodel}</span></td>
                    <td style="font-size:13px;max-width:200px;color:#64748b">{pdesc if pdesc else '-'}</td>
                    <td style="text-align:center">{ppriority}</td>
                    <td style="text-align:center;font-weight:600">{pusage}</td>
                    <td style="text-align:center;color:#64748b">{has_custom}</td>
                </tr>"""
            
            if not persona_rows:
                persona_rows = '<tr><td colspan="7" style="color:#94a3b8;text-align:center;padding:24px">No personas configured</td></tr>'
            
            personas_html = f"""<div class="card">
                <h2>&#129302; AI Personas</h2>
                <p style="font-size:13px;color:#64748b;margin-bottom:12px">AI personas generate diverse comments from different perspectives.</p>
                <div style="overflow-x:auto">
                <table>
                <thead><tr>
                    <th>ID</th>
                    <th>Author</th>
                    <th>Model</th>
                    <th>Description</th>
                    <th style="text-align:center">Priority</th>
                    <th style="text-align:center">Usage</th>
                    <th style="text-align:center">Custom</th>
                </tr></thead>
                <tbody>{persona_rows}</tbody>
                </table>
                </div>
            </div>"""
        except Exception as e:
            personas_html = f'<div class="card"><h2>&#129302; AI Personas</h2><div class="msg-err">Error loading personas: {_esc(str(e))}</div></div>'

        # --- Generate Comment for Specific Link ---
        gen_comment_html = """<div class="card">
            <h2>&#128172; Generate Comment</h2>
            <p style="font-size:13px;color:#64748b;margin-bottom:12px">Manually generate AI comments for a specific link.</p>
            <form method="POST" action="/admin/ai/generate-comment" style="display:flex;gap:8px;flex-wrap:wrap;align-items:end">
                <div style="flex:1;min-width:150px">
                    <label style="font-size:12px;color:#64748b;display:block;margin-bottom:2px">Link ID</label>
                    <input type="number" name="link_id" placeholder="123" required style="width:100%">
                </div>
                <button class="btn btn-primary" type="submit">&#128172; Generate Comment</button>
            </form>
        </div>"""

        # --- Assemble ---
        body = _messages(message, error)
        body += health_html
        body += '<div class="grid-2">'
        body += token_html
        body += '<div>' + discover_html + enrich_html + gen_comment_html + '</div>'
        body += '</div>'
        body += personas_html
        body += runs_html
        body += content_html

        return HTMLResponse(_page("AI Engine", body))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(_page("AI Engine - Error", f'<div class="msg-err">Error: {_esc(str(e))}</div>'))


@app.post("/admin/ai/discover")
async def admin_ai_discover(background_tasks: BackgroundTasks,
                             topic: str = Form(""),
                             count: int = Form(5),
                             source: str = Form("hn"),
                             admin: str = Depends(verify_admin)):
    engine = _get_ai_engine()
    topic = topic.strip() or None

    if count <= 5:
        try:
            result = await engine.discover_links(topic=topic, source=source, count=count)
            discovered = result.get("discovered", 0)
            err = result.get("error")
            if err:
                return RedirectResponse(
                    url=f"/admin/ai?error=Discovery error: {err}",
                    status_code=303)
            return RedirectResponse(
                url=f"/admin/ai?message=Discovered {discovered} new links",
                status_code=303)
        except Exception as e:
            return RedirectResponse(
                url=f"/admin/ai?error={e}",
                status_code=303)
    else:
        async def _run():
            await engine.discover_links(topic=topic, source=source, count=count)
        background_tasks.add_task(_run)
        return RedirectResponse(
            url=f"/admin/ai?message=Discovery started in background ({count} links, source: {source})",
            status_code=303)


@app.post("/admin/ai/enrich")
async def admin_ai_enrich(background_tasks: BackgroundTasks,
                           limit: int = Form(5),
                           types: list = Form([]),
                           admin: str = Depends(verify_admin)):
    engine = _get_ai_engine()
    if not types:
        types = ["description", "tags", "comments"]

    if limit <= 3:
        try:
            result = await engine.enrich_batch(limit=limit, types=types)
            enriched = result.get("enriched", 0)
            return RedirectResponse(
                url=f"/admin/ai?message=Enriched {enriched} links",
                status_code=303)
        except Exception as e:
            return RedirectResponse(
                url=f"/admin/ai?error={e}",
                status_code=303)
    else:
        async def _run():
            await engine.enrich_batch(limit=limit, types=types)
        background_tasks.add_task(_run)
        return RedirectResponse(
            url=f"/admin/ai?message=Enrichment started in background ({limit} links)",
            status_code=303)


@app.post("/admin/ai/generate-comment")
async def admin_ai_generate_comment_form(
    background_tasks: BackgroundTasks,
    link_id: int = Form(...),
    admin: str = Depends(verify_admin)
):
    """HTML form handler to generate AI comment for a specific link."""
    try:
        engine = _get_ai_engine()
        result = await engine.enrich_link(link_id, types=["comments"])
        
        comments = result.get("generated", {}).get("comments", [])
        if comments:
            return RedirectResponse(
                url=f"/admin/ai?message=Generated {len(comments)} comment(s) for link {link_id}",
                status_code=303
            )
        elif result.get("error"):
            return RedirectResponse(
                url=f"/admin/ai?error=Error: {result['error']}",
                status_code=303
            )
        else:
            return RedirectResponse(
                url=f"/admin/ai?message=No new comments generated (may already exist)",
                status_code=303
            )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/ai?error=Error: {str(e)}",
            status_code=303
        )


# ============================================================
# Admin API Endpoints (JSON)
# ============================================================

from backoff import get_backoff_status

@app.get("/api/admin/queue-status")
async def api_admin_queue_status(admin: str = Depends(verify_admin)):
    """Get processing queue status."""
    try:
        # Count links by processing status
        new_count = supabase.table("links").select("id", count="exact").eq("processing_status", "new").execute()
        processing_count = supabase.table("links").select("id", count="exact").eq("processing_status", "processing").execute()
        completed_count = supabase.table("links").select("id", count="exact").eq("processing_status", "completed").execute()
        failed_count = supabase.table("links").select("id", count="exact").eq("processing_status", "failed").execute()
        
        # Priority breakdown - user-submitted vs RSS
        user_submitted = supabase.table("links").select("id", count="exact").eq("source", "scratchpad").eq("processing_status", "new").execute()
        rss_links = supabase.table("links").select("id", count="exact").neq("source", "scratchpad").eq("processing_status", "new").execute()
        
        return {
            "queue": {
                "new": new_count.count if hasattr(new_count, 'count') else len(new_count.data or []),
                "processing": processing_count.count if hasattr(processing_count, 'count') else len(processing_count.data or []),
                "completed": completed_count.count if hasattr(completed_count, 'count') else len(completed_count.data or []),
                "failed": failed_count.count if hasattr(failed_count, 'count') else len(failed_count.data or []),
            },
            "priority_breakdown": {
                "user_submitted": user_submitted.count if hasattr(user_submitted, 'count') else len(user_submitted.data or []),
                "rss_feeds": rss_links.count if hasattr(rss_links, 'count') else len(rss_links.data or []),
            }
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/admin/api-health")
async def api_admin_api_health(admin: str = Depends(verify_admin)):
    """Get API health/backoff status for all tracked APIs."""
    try:
        apis = ["anthropic", "reddit", "hackernews"]
        health = {}
        
        for api_name in apis:
            status = get_backoff_status(api_name)
            health[api_name] = {
                "status": "backing_off" if status.get("is_backing_off") else "ok",
                "consecutive_failures": status.get("consecutive_failures", 0),
                "backoff_until": status.get("backoff_until"),
                "last_success_at": str(status.get("last_success_at")) if status.get("last_success_at") else None,
                "last_failure_at": str(status.get("last_failure_at")) if status.get("last_failure_at") else None,
                "last_error": status.get("last_error"),
            }
        
        return {"apis": health}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/admin/budget-status")
async def api_admin_budget_status(admin: str = Depends(verify_admin)):
    """Get monthly AI budget status."""
    try:
        # Get current month's usage from ai_token_usage
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        usage_resp = supabase.table("ai_token_usage").select(
            "estimated_cost_usd"
        ).gte("created_at", month_start.isoformat()).execute()
        
        total_cost = sum(float(r.get("estimated_cost_usd", 0) or 0) for r in (usage_resp.data or []))
        budget = 50.0  # $50 monthly budget
        
        return {
            "current_spend": round(total_cost, 4),
            "budget": budget,
            "percentage": round((total_cost / budget) * 100, 1),
            "remaining": round(budget - total_cost, 4),
            "month": now.strftime("%Y-%m"),
            "warning": total_cost > (budget * 0.8),  # Warning if > 80%
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/admin/job-runs")
async def api_admin_job_runs(limit: int = 20, admin: str = Depends(verify_admin)):
    """Get recent job runs."""
    try:
        # Try job_runs table first (if exists), fall back to ai_runs
        try:
            runs_resp = supabase.table("job_runs").select("*").order("started_at", desc=True).limit(limit).execute()
            runs = runs_resp.data or []
        except Exception:
            # Fall back to ai_runs table
            runs_resp = supabase.table("ai_runs").select(
                "id, type, status, results_count, tokens_used, created_at, completed_at, error"
            ).order("created_at", desc=True).limit(limit).execute()
            runs = []
            for r in (runs_resp.data or []):
                # Calculate duration if both timestamps exist
                duration = None
                if r.get("created_at") and r.get("completed_at"):
                    try:
                        start = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                        end = datetime.fromisoformat(r["completed_at"].replace("Z", "+00:00"))
                        duration = int((end - start).total_seconds())
                    except Exception:
                        pass
                
                runs.append({
                    "id": r.get("id"),
                    "type": r.get("type"),
                    "status": r.get("status"),
                    "started_at": r.get("created_at"),
                    "completed_at": r.get("completed_at"),
                    "duration_seconds": duration,
                    "items_processed": r.get("results_count"),
                    "error": r.get("error"),
                })
        
        return {"job_runs": runs}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/admin/ai-discover/hn")
async def api_admin_ai_discover_hn(background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    """Manually trigger AI-based Hacker News link discovery (web search, not RSS)."""
    try:
        engine = _get_ai_engine()
        
        async def _run():
            return await engine.discover_links(source="hn", count=10)
        
        background_tasks.add_task(_run)
        return {"status": "started", "message": "AI HN discovery started in background"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/admin/ai-discover/reddit")
async def api_admin_ai_discover_reddit(background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    """Manually trigger AI-based Reddit link discovery (web search, not RSS)."""
    try:
        engine = _get_ai_engine()
        
        async def _run():
            return await engine.discover_links(source="reddit", count=10)
        
        background_tasks.add_task(_run)
        return {"status": "started", "message": "AI Reddit discovery started in background"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/admin/ai/enrich")
async def api_admin_ai_enrich(background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    """Manually trigger AI enrichment batch (summaries, descriptions, comments via AI engine)."""
    try:
        engine = _get_ai_engine()
        
        async def _run():
            return await engine.enrich_batch(limit=5, types=["summary", "description", "comments"])
        
        background_tasks.add_task(_run)
        return {"status": "started", "message": "AI enrichment batch started in background"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/admin/generate-comment/{link_id}")
async def api_admin_generate_comment(link_id: int, background_tasks: BackgroundTasks, admin: str = Depends(verify_admin)):
    """Manually generate AI comment for a specific link."""
    try:
        engine = _get_ai_engine()
        
        async def _run():
            return await engine.enrich_link(link_id, types=["comments"])
        
        background_tasks.add_task(_run)
        return {"status": "started", "message": f"Generating comment for link {link_id}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('PORT', 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
