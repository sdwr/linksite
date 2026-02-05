# External API Refactor Plan — Reddit/HN Discussion Lookup

## Current Architecture Analysis

### Reddit API Usage Points

| Location | Function | API Call | Rate Limited? |
|----------|----------|----------|---------------|
| `scratchpad_api.py` | `_reddit_api_get()` | Central wrapper | ✅ Yes (30/min) |
| `scratchpad_api.py` | `find_external_discussions()` | `/search?q=url:{url}` | ✅ Via wrapper |
| `scratchpad_api.py` | `resolve_reddit_url()` | `/{path}.json` | ✅ Via wrapper |
| `scratchpad_api.py` | `resolve_reddit_url()` fallback | Public `.json` endpoint | ❌ No |

### HN API Usage Points

| Location | Function | API Call | Rate Limited? |
|----------|----------|----------|---------------|
| `scratchpad_api.py` | `find_external_discussions()` | HN Algolia `/search` | ❌ No |
| `scratchpad_api.py` | `resolve_hn_url()` | HN Algolia `/items/{id}` | ❌ No |

### Reddit Stats Storage

```
In-memory: _reddit_stats dict
  - total_calls, searches, resolves, token_refreshes
  - last_call_time, last_error, last_error_time

Persisted to: global_state.reddit_api_stats (JSONB)
  - Loaded on startup via _load_reddit_stats_from_db()
  - Saved after each API call via _save_reddit_stats_to_db()
```

### Where External Calls Are Triggered (The Problem)

#### 1. Immediate Background Threads (BYPASSES QUEUE)
```python
# scratchpad_api.py - ingest_link_async()
def _ext_disc():
    time.sleep(2)
    fetch_and_save_external_discussions(link_id, url)  # ← Immediate Reddit/HN calls
    check_reverse_lookup(url, link_id)                  # ← More API calls
ext_thread = threading.Thread(target=_ext_disc, daemon=True)
ext_thread.start()
```

**Problem:** Every new link immediately spawns threads that hit Reddit/HN APIs.

#### 2. Worker Processing (PROPER QUEUE)
```python
# worker.py - run_processing_batch()
if not existing_disc and url:
    await run_external_discussion_lookup(link_id, url)  # ← Respects rate limits
```

**This is correct** but often the work is already done by the immediate threads.

#### 3. Manual Endpoint (BYPASSES QUEUE)
```python
# POST /api/link/{id}/find-discussions
thread = threading.Thread(target=_run, daemon=True)
thread.start()  # ← No rate limiting
```

### URL Unwrapping vs Reverse Lookup

| Operation | What It Does | Uses Reddit API? |
|-----------|--------------|------------------|
| **URL Unwrapping** | Resolve bit.ly → final URL | No (HTTP redirects only) |
| **Reverse Lookup** | Reddit post URL → original article | **Yes** (`resolve_reddit_url()`) |
| **Discussion Search** | Any URL → find Reddit/HN threads | **Yes** (`find_external_discussions()`) |

**Answer:** URL unwrapping is NOT currently implemented. Reverse lookup does use Reddit API.

---

## Problems with Current System

### 1. Race Conditions & Rate Limit Bypass
- Background threads spawned immediately on link submission
- These threads bypass the worker queue and its rate limiting
- Can hit rate limits before worker even processes the link

### 2. Duplicate Work
- External discussions fetched TWICE:
  1. Immediately via `ingest_link_async()` background thread
  2. Later via worker's `run_processing_batch()` (if not already done)
- Wastes API quota

### 3. No HN Rate Limiting
- HN Algolia calls have no rate limiting
- Algolia is generous but could still be abused
- Should use existing backoff.py infrastructure

### 4. No Prioritization
- All links treated equally for external lookups
- User-submitted links should get priority
- Recent links should be processed before backlog

### 5. Unpredictable Timing
- External API calls happen immediately on submission
- No control over when Reddit API gets hit
- Can't batch or schedule efficiently

---

## Proposed Solution

### Phase 1: Remove Immediate External Calls

**Change `ingest_link_async()` to NOT trigger external lookups:**

```python
# BEFORE (scratchpad_api.py)
def ingest_link_async(link_id: int, url: str):
    def _ingest():
        # ... content extraction ...
    thread = threading.Thread(target=_ingest, daemon=True)
    thread.start()
    
    # REMOVE THIS ENTIRE BLOCK:
    def _ext_disc():
        time.sleep(2)
        fetch_and_save_external_discussions(link_id, url)
        check_reverse_lookup(url, link_id)
    ext_thread = threading.Thread(target=_ext_disc, daemon=True)
    ext_thread.start()

# AFTER
def ingest_link_async(link_id: int, url: str):
    def _ingest():
        # ... content extraction ...
    thread = threading.Thread(target=_ingest, daemon=True)
    thread.start()
    # External lookups now handled by worker queue
```

**Impact:** 
- ✅ No more immediate Reddit/HN API calls on link submission
- ✅ All external lookups go through worker queue
- ⚠️ Slight delay before discussions appear (worker runs every 90s)

### Phase 2: Add HN Rate Limiting

**Add HN to backoff.py RATE_LIMITS:**

```python
RATE_LIMITS = {
    'reddit': {'requests_per_minute': 30, 'window_seconds': 60},
    'anthropic': {'requests_per_minute': 50, 'window_seconds': 60},
    'hackernews': {'requests_per_minute': 60, 'window_seconds': 60},  # Already defined!
}
```

**Wrap HN calls in rate limiting:**

```python
def find_external_discussions(url: str) -> list:
    results = []
    
    # 1. Hacker News via Algolia - ADD RATE LIMITING
    if check_rate_limit("hackernews"):
        record_request("hackernews")
        try:
            resp = httpx.get("https://hn.algolia.com/api/v1/search", ...)
            # ...
        except Exception as e:
            record_failure("hackernews", str(e))
    
    # 2. Reddit via OAuth API
    # (already rate limited)
```

### Phase 3: Prioritized Processing Queue

**New priority scoring for external lookups:**

```python
# worker.py - get links needing external lookups
def get_links_for_external_lookup(limit: int = 20) -> list:
    """
    Get links that need external discussion lookup, prioritized by:
    1. User-submitted (source='agent', submitted_by not auto)
    2. Reddit/HN source (likely to have discussions)
    3. Recent (last 24h)
    4. Everything else (backlog)
    """
    return query("""
        SELECT id, url, source, submitted_by, created_at
        FROM links
        WHERE processing_status IN ('new', 'completed')
          AND (external_lookup_at IS NULL 
               OR external_lookup_at < NOW() - INTERVAL '7 days')
          AND source NOT IN ('auto-parent', 'discussion-ref')
        ORDER BY 
            CASE 
                WHEN source = 'agent' OR submitted_by NOT IN ('auto', 'gatherer') THEN 0
                WHEN source IN ('reddit', 'hn') THEN 1
                WHEN created_at > NOW() - INTERVAL '24 hours' THEN 2
                ELSE 3
            END,
            created_at DESC
        LIMIT %s
    """, (limit,))
```

**Add `external_lookup_at` column to links table:**

```sql
ALTER TABLE links ADD COLUMN external_lookup_at TIMESTAMPTZ;
CREATE INDEX idx_links_external_lookup ON links(external_lookup_at) 
    WHERE external_lookup_at IS NULL;
```

### Phase 4: Separate External Lookup Worker

**Split worker into two functions:**

```python
# worker.py

async def run_external_lookup_batch(batch_size: int = 10) -> dict:
    """
    Batch external discussion lookups only.
    Runs more frequently than AI summarization.
    Cheaper (API calls, not AI tokens).
    """
    links = get_links_for_external_lookup(batch_size)
    
    for link in links:
        # Check rate limits for both APIs
        reddit_ok = check_rate_and_backoff("reddit")
        hn_ok = check_rate_and_backoff("hackernews")
        
        if not reddit_ok and not hn_ok:
            print("[Worker] Both APIs rate limited, stopping batch")
            break
        
        await run_external_discussion_lookup(
            link["id"], 
            link["url"],
            skip_reddit=not reddit_ok,
            skip_hn=not hn_ok
        )
        
        # Update timestamp
        execute(
            "UPDATE links SET external_lookup_at = NOW() WHERE id = %s",
            (link["id"],)
        )
    
    return {"processed": len(links)}

async def run_summary_batch(batch_size: int = 10) -> dict:
    """
    Batch AI summarization only.
    Runs less frequently, respects budget.
    """
    # ... existing summary logic ...
```

**Adjust worker loop:**

```python
async def _worker_loop(interval_seconds: int = 90):
    while _worker_running:
        # External lookups every cycle (cheap)
        await run_external_lookup_batch(batch_size=10)
        
        # Summaries less frequently (expensive)
        if cycle_count % 4 == 0:  # Every 4th cycle = every 6 minutes
            await run_summary_batch(batch_size=5)
        
        await asyncio.sleep(interval_seconds)
```

### Phase 5: Rate-Limit the Manual Endpoint

**Fix `/api/link/{id}/find-discussions`:**

```python
@router.post("/api/link/{link_id}/find-discussions")
async def api_find_discussions(link_id: int):
    # Check rate limits first
    if not check_rate_and_backoff("reddit") and not check_rate_and_backoff("hackernews"):
        raise HTTPException(429, "Rate limited, try again later")
    
    # Queue it instead of immediate execution
    execute(
        "UPDATE links SET external_lookup_at = NULL WHERE id = %s",
        (link_id,)
    )
    
    return {"ok": True, "message": "Queued for discussion lookup"}
```

---

## Implementation Order

| Phase | Description | Files Changed | Risk |
|-------|-------------|---------------|------|
| **1** | Remove immediate external calls | `scratchpad_api.py` | Low |
| **2** | Add HN rate limiting | `scratchpad_api.py` | Low |
| **3** | Add priority queue | `worker.py`, DB migration | Medium |
| **4** | Separate worker functions | `worker.py` | Medium |
| **5** | Rate-limit manual endpoint | `scratchpad_api.py` | Low |

**Recommended:** Do Phase 1 + 2 first (quick wins), then 3-5 together.

---

## Impact Analysis

### Positive Impacts

1. **Predictable API usage** — All calls go through rate-limited queue
2. **No race conditions** — Single worker controls timing
3. **User experience priority** — Submitted links processed first
4. **Efficient backlog processing** — Old links get checked during quiet periods
5. **Reduced duplicate work** — External lookups tracked, not repeated

### Potential Negative Impacts

1. **Slight delay for new links** — Discussions won't appear immediately
   - Mitigation: Worker runs every 90s, fast enough for most cases
   
2. **Migration complexity** — Need new DB column
   - Mitigation: Simple ALTER TABLE, backward compatible

3. **Testing needed** — Worker logic is more complex
   - Mitigation: Add logging, monitor via admin dashboard

### Breaking Changes

None expected. All changes are internal to how/when API calls happen.

---

## Questions to Resolve

1. **Re-check interval:** How often should we re-check links for new discussions?
   - Current plan: 7 days
   - Could be configurable per-source

2. **Skip vs Fail:** If Reddit is rate-limited but HN isn't, should we:
   - Skip Reddit for this link (current plan)
   - Or retry the whole link later?

3. **Manual trigger behavior:** Should `/find-discussions` be:
   - Queue-only (current plan)
   - Or immediate with rate check?

---

## DB Migration Required

```sql
-- Add external lookup tracking
ALTER TABLE links ADD COLUMN external_lookup_at TIMESTAMPTZ;

-- Index for finding links needing lookup
CREATE INDEX idx_links_needs_external_lookup 
ON links(created_at DESC) 
WHERE external_lookup_at IS NULL 
  AND source NOT IN ('auto-parent', 'discussion-ref');

-- Comment
COMMENT ON COLUMN links.external_lookup_at IS 
    'Last time external discussions were fetched. NULL = never checked.';
```

---

*Plan created: 2025-01-17*
