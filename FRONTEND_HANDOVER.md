# Linksite Frontend API Handover

## 1. Architecture Overview

Linksite uses a **Director-driven real-time architecture**:

- A **Director** (async background task) rotates a "featured" link every ~120 seconds
- **Satellite links** orbit the featured link, revealed progressively over time
- Users **react** (like/dislike) to the featured link, which adjusts its display timer
- Users **nominate** satellites to influence what gets featured next
- All state streams to clients via **Server-Sent Events (SSE)**
- User actions are sent via **POST requests** and instantly broadcast to all connected clients

```
┌──────────────────────────────────────────────────────────────────┐
│                        REAL-TIME FLOW                            │
│                                                                  │
│   Browser A ──POST /react──▶ FastAPI ──broadcast──▶ All SSE     │
│   Browser B ──POST /nominate──▶ FastAPI ──broadcast──▶ All SSE  │
│                                   ▲                              │
│                                   │                              │
│                            Director Loop                         │
│                          (tick every 2s)                          │
│                      rotates featured link                       │
│                      reveals satellites                          │
│                      adjusts timers                              │
└──────────────────────────────────────────────────────────────────┘
```

## 2. Voting Model

### Reactions (Like / Dislike)

- **Target:** The currently featured link
- **Effect:** `+1` adds time to the feature timer; `-1` subtracts time
- **Score:** Updates `links.direct_score` field (cumulative)
- **Cooldown:** Configurable (default 10s) per user between reactions
- **Threshold:** Enough downvotes from a single user can trigger an immediate skip

### Nominations

- **Target:** Any satellite link in the current rotation
- **Effect:** Votes that satellite to be featured next when the current rotation ends
- **Score boost:** Each nomination gives the link +0.5 `direct_score`
- **Scope:** Nominations are scoped to the current rotation — cleared on rotate
- **Limit:** One nomination per user per rotation (re-nominating changes your pick)
- **Director behavior:** When rotating, the Director picks the most-nominated satellite. On ties or no nominations, falls back to normal pool selection (fresh/rerun/wildcard)

---

## 3. API Reference

### `GET /api/stream` — SSE Real-Time Stream

Connect via `EventSource`. Receives JSON payloads as `data:` lines.

**Headers returned:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

**Heartbeat (every ~2s):** Full state snapshot:
```json
{
    "type": "state",
    "featured": {
        "link": {
            "id": 42,
            "title": "How Neural Networks Actually Work",
            "url": "https://example.com/neural-nets",
            "feed_name": "tech-blog"
        },
        "time_remaining_sec": 87.3,
        "total_duration_sec": 120,
        "reason": "fresh",
        "started_at": "2025-01-28T10:30:00+00:00"
    },
    "satellites": [
        {
            "id": 5,
            "title": "Deep Learning Fundamentals",
            "url": "https://example.com/deep-learning",
            "position": "top",
            "label": "Deep Dive",
            "revealed": true,
            "nominations": 3
        },
        {
            "id": 12,
            "title": "Why Rust is Taking Over",
            "url": "https://example.com/rust",
            "position": "top-left",
            "label": "Pivot",
            "revealed": false,
            "nominations": 0
        }
    ],
    "recent_actions": [
        {"type": "react", "link_id": 42, "value": 1, "user_id": "a1b2c3d4-e5f6", "ago_sec": 1.2},
        {"type": "nominate", "link_id": 5, "user_id": "x7y8z9w0-a1b2", "ago_sec": 4.5}
    ],
    "viewer_count": 3,
    "server_time": "2025-01-28T10:31:33+00:00"
}
```

**Immediate events** (pushed between heartbeats):
```json
{"type": "react", "link_id": 42, "value": 1, "user_id": "a1b2c3d4-e5f6"}
```
```json
{"type": "nominate", "link_id": 5, "user_id": "x7y8z9w0-a1b2"}
```
```json
{
    "type": "rotation",
    "new_link": {"id": 5, "title": "Deep Learning Fundamentals", "url": "..."},
    "reason": "nominated"
}
```

---

### `GET /api/now` — One-Shot State (Fallback)

Returns full state as a single JSON response. Use as fallback if SSE isn't available or for initial page load.

**Response:**
```json
{
    "link": {
        "id": 42,
        "url": "https://example.com/neural-nets",
        "title": "How Neural Networks Actually Work",
        "meta_json": {},
        "direct_score": 7,
        "feed_id": 3
    },
    "tags": [
        {"name": "tech", "slug": "tech"}
    ],
    "satellites": [
        {
            "link_id": 5,
            "title": "Deep Learning Fundamentals",
            "url": "...",
            "position": "top",
            "label": "Deep Dive",
            "reveal_at": "2025-01-28T10:30:20+00:00",
            "revealed": true,
            "nominations": 3
        }
    ],
    "timers": {
        "started_at": "2025-01-28T10:30:00+00:00",
        "reveal_ends_at": "2025-01-28T10:31:40+00:00",
        "rotation_ends_at": "2025-01-28T10:32:00+00:00",
        "seconds_remaining": 87
    },
    "votes": {
        "score": 7,
        "my_votes_count": 1,
        "my_last_vote_at": "2025-01-28T10:30:45+00:00"
    },
    "selection_reason": "fresh",
    "viewer_count": 3
}
```

---

### `POST /api/links/{id}/react` — React to Featured Link

**Body:**
```json
{"value": 1}
```
- `1` = like (adds display time, +1 score)
- `-1` = dislike (reduces display time, -1 score)

**Response (200):**
```json
{"ok": true, "value": 1, "new_score": 8}
```

**Errors:**
- `400` — value not 1 or -1
- `429` — cooldown active (wait N seconds)

> **Alias:** `POST /api/links/{id}/vote` works identically (backward compat).

---

### `POST /api/links/{id}/nominate` — Nominate a Satellite

**Body:**
```json
{"user_id": "optional-override"}
```
- `user_id` is optional; defaults to the cookie-based identity
- `id` must be a current satellite's `link_id`
- One nomination per user per rotation (re-nominates update your pick)

**Response (200):**
```json
{"ok": true, "nominations": 4}
```

**Errors:**
- `400` — no active rotation, or link is not a current satellite

---

### `GET /api/links/{id}/votes` — Vote Counts for a Link

**Response:**
```json
{
    "score": 7,
    "my_votes_count": 2,
    "my_last_vote_at": "2025-01-28T10:30:45+00:00"
}
```

---

### `GET /api/links/{id}/nominations` — Nomination Count

**Response:**
```json
{"link_id": 5, "nominations": 3}
```

---

### `GET /api/links/{id}/tags` — Tags for a Link

**Response:**
```json
[
    {"name": "tech", "slug": "tech", "score": 12.5},
    {"name": "ai", "slug": "ai", "score": 8.2}
]
```

---

### `GET /api/tags/top` — Top Tags

**Response:**
```json
[
    {"id": 1, "name": "tech", "slug": "tech", "score": 45.2},
    {"id": 3, "name": "gaming", "slug": "gaming", "score": 32.1}
]
```

---

### `GET /api/weights` — Score Weights (read-only for frontend)

Returns configurable parameters. Useful for frontend display logic.

```json
[
    {"key": "rotation_default_sec", "value": 120},
    {"key": "reveal_interval_sec", "value": 20},
    {"key": "vote_cooldown_sec", "value": 10},
    {"key": "satellite_count", "value": 5}
]
```

---

## 4. Frontend Integration Guide

### Connecting to SSE

```javascript
const BASE = 'https://linksite-dev-bawuw.sprites.app';
let eventSource = null;

function connectSSE() {
    eventSource = new EventSource(`${BASE}/api/stream`);
    
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        switch (data.type) {
            case 'state':
                updateFullState(data);
                break;
            case 'react':
                showReactionAnimation(data);
                break;
            case 'nominate':
                updateNominationCount(data);
                break;
            case 'rotation':
                handleRotation(data);
                break;
        }
    };
    
    eventSource.onerror = () => {
        // Auto-reconnects. Optionally show "reconnecting..." UI
        console.log('SSE connection lost, reconnecting...');
    };
}
```

### Page Visibility API (Disconnect When Hidden)

Save resources by disconnecting when the tab is hidden:

```javascript
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    } else {
        if (!eventSource) {
            connectSSE();
        }
    }
});
```

### Anonymous User Identity

The backend sets a `user_id` cookie automatically on first request. For frontend-initiated identity:

```javascript
function getUserId() {
    let id = localStorage.getItem('linksite_user_id');
    if (!id) {
        id = 'anon_' + crypto.randomUUID().slice(0, 8);
        localStorage.setItem('linksite_user_id', id);
    }
    return id;
}
```

The cookie-based identity (set by middleware) is the authoritative one for rate limiting. The `user_id` in POST bodies is optional and mainly for display purposes.

### Sending Reactions

```javascript
async function react(linkId, value) {
    const res = await fetch(`${BASE}/api/links/${linkId}/react`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',  // send cookies
        body: JSON.stringify({ value }),
    });
    
    if (res.status === 429) {
        // Cooldown — show "wait..." UI
        const data = await res.json();
        showCooldown(data.detail);
        return;
    }
    
    const data = await res.json();
    // Optimistic update — real state arrives via SSE
    updateScoreDisplay(data.new_score);
}
```

### Sending Nominations

```javascript
async function nominate(linkId) {
    const res = await fetch(`${BASE}/api/links/${linkId}/nominate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({}),
    });
    
    const data = await res.json();
    // data.nominations = updated count for this link
    updateNominationBadge(linkId, data.nominations);
}
```

### Recommended UI Update Patterns

1. **Timer countdown:** Client-side `requestAnimationFrame` or `setInterval(1s)` counting down from `time_remaining_sec`. Recalibrate on each SSE state message.

2. **Optimistic updates:** When the user reacts/nominates, update UI immediately. SSE will confirm or correct.

3. **Satellite reveal:** Check `revealed` boolean. Animate reveal when it flips from `false` → `true` between state updates.

4. **Viewer count:** Display directly from `viewer_count` in state updates. Updates every 2s automatically.

5. **Rotation transition:** On `type: "rotation"` events, play a transition animation, then let the next `type: "state"` heartbeat populate the new data.

---

## 5. Data Flow Diagram

```
┌─────────────┐      POST /react       ┌──────────────────────┐
│  Browser A   │ ─────────────────────▶ │                      │
│  (viewer)    │                        │     FastAPI Server    │
│              │ ◀─────────────────── │                      │
│              │   SSE: {type:"react"}  │  ┌────────────────┐  │
└─────────────┘                        │  │  Director Loop  │  │
                                        │  │  (tick / 2s)    │  │
┌─────────────┐   POST /nominate        │  │                │  │
│  Browser B   │ ─────────────────────▶ │  │  • Check timer  │  │
│  (viewer)    │                        │  │  • Adjust votes │  │
│              │ ◀─────────────────── │  │  • Rotate?      │  │
│              │   SSE: {type:"state"}  │  │  • Check noms   │  │
└─────────────┘                        │  └────────────────┘  │
                                        │          │           │
┌─────────────┐                        │          ▼           │
│  Browser C   │ ◀─────────────────── │   broadcast_event()  │
│  (viewer)    │   SSE: {type:"state"}  │          │           │
│              │   SSE: {type:"rotation"}│         ▼           │
└─────────────┘                        │  ┌──────────────┐   │
                                        │  │  Supabase DB  │   │
                                        │  │  • links      │   │
                                        │  │  • votes      │   │
                                        │  │  • nominations│   │
                                        │  │  • global_state│  │
                                        │  └──────────────┘   │
                                        └──────────────────────┘

FLOW:
1. User clicks "like" → POST /api/links/42/react {value: 1}
2. Server records vote in DB, updates link score
3. Server calls record_action() → adds to recent_actions + broadcast_event()
4. broadcast_event() pushes {type: "react"} to ALL connected SSE queues
5. All browsers receive the event via their EventSource connection
6. Next Director tick: reads votes, adjusts timer, may rotate
7. On rotation: Director checks nominations, picks next link, broadcasts {type: "rotation"}
8. Every 2s: SSE heartbeat sends full {type: "state"} to all clients
```

---

## 6. Satellite Positions

The Director assigns satellites to named positions:
- `"top"` — above the featured link
- `"top-left"` — upper left orbit
- `"top-right"` — upper right orbit
- `"left"` — left orbit
- `"right"` — right orbit

Each satellite also has a `label` describing its relationship:
- `"Deep Dive"` — related/similar content
- `"Pivot"` — different angle/topic shift
- `"Wildcard"` — random/surprising pick

---

## 7. Timing Reference

| Parameter | Default | Description |
|---|---|---|
| `rotation_default_sec` | 120 | Base featured link duration |
| `reveal_interval_sec` | 20 | Seconds between satellite reveals |
| `vote_cooldown_sec` | 10 | Min seconds between user reactions |
| `upvote_time_bonus_sec` | 15 | Seconds added per like |
| `downvote_time_penalty_sec` | 20 | Seconds removed per dislike |
| `downvote_skip_threshold` | 3 | Downvotes from 1 user to force skip |
| `satellite_count` | 5 | Number of satellites per rotation |
| `fatigue_lookback` | 20 | Recent rotations to avoid repeating |

All values are configurable via the admin dashboard (`/admin`) or `POST /api/weights/{key}`.
