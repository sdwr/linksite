# External API Rate Limiting — Final Implementation Plan

## Current State Summary

### DB Schema (Current)
- `links.processing_status` — covers BOTH summary AND external discussions (no separation)
- `links.last_processed_at` — when last processed
- All processing state mixed into the main `links` table

### Problem with Current Approach
- `links` table has mixed concerns (content + processing state)
- Every worker update creates dead tuples in the main table
- Feed queries pull processing columns they don't need
- Hard to track per-task status (Reddit vs HN vs Summary)

### Where Reddit/HN API Calls Happen

| Location | What | When | Rate Limited? |
|----------|------|------|---------------|
| `scratchpad_routes.py` POST /add | `resolve_reddit_url()` / `resolve_hn_url()` | User submits discussion URL | ❌ No |
| `scratchpad_api.py` `ingest_link_async()` | `fetch_and_save_external_discussions()` + `check_reverse_lookup()` | Background thread on link creation | ❌ Bypasses queue |
| `worker.py` `run_processing_batch()` | `run_external_discussion_lookup()` | Worker queue tick | ✅ Yes |

**Problems:**
1. Web form does SYNCHRONOUS reverse lookup (blocks user)
2. `ingest_link_async()` does redundant reverse lookup in background
3. Three places making API calls, only one is rate-limited

---

## Implementation Plan

### Phase 1: DB Migration — Create `link_processing` Table

**Design:** 1-to-1 relationship with `links`. Keeps main table thin, isolates worker churn.

```sql
-- New processing status table (1-to-1 with links)
CREATE TABLE link_processing (
    link_id BIGINT PRIMARY KEY REFERENCES links(id) ON DELETE CASCADE,
    
    -- Reddit discussion lookup
    reddit_status TEXT DEFAULT 'pending',  -- pending, completed, not_found, failed
    reddit_checked_at TIMESTAMPTZ,
    reddit_error TEXT,
    
    -- HN discussion lookup  
    hn_status TEXT DEFAULT 'pending',      -- pending, completed, not_found, failed
    hn_checked_at TIMESTAMPTZ,
    hn_error TEXT,
    
    -- AI summary generation
    summary_status TEXT DEFAULT 'pending', -- pending, completed, skipped, failed
    summary_generated_at TIMESTAMPTZ,
    summary_error TEXT,
    
    -- General tracking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- For reverse lookup (Reddit/HN URL → original article)
    reverse_lookup_status TEXT,            -- NULL (not needed), pending, completed, failed
    reverse_lookup_target_id BIGINT REFERENCES links(id)  -- The resolved article link
);

-- Index for worker: find links needing Reddit lookup
CREATE INDEX idx_link_processing_reddit_pending 
ON link_processing(created_at) 
WHERE reddit_status = 'pending';

-- Index for worker: find links needing HN lookup
CREATE INDEX idx_link_processing_hn_pending 
ON link_processing(created_at) 
WHERE hn_status = 'pending';

-- Index for worker: find links needing summary
CREATE INDEX idx_link_processing_summary_pending 
ON link_processing(created_at) 
WHERE summary_status = 'pending';

-- Index for reverse lookup queue
CREATE INDEX idx_link_processing_reverse_pending
ON link_processing(created_at)
WHERE reverse_lookup_status = 'pending';

COMMENT ON TABLE link_processing IS 
    'Processing state for links. 1-to-1 with links table. Isolates worker churn from main table.';
```

**Status values:**
- `pending` — needs processing
- `completed` — successfully processed
- `not_found` — processed but no results (e.g., no Reddit discussions exist)
- `failed` — error occurred (see `*_error` column)
- `skipped` — intentionally skipped (e.g., summary skipped due to budget)

**Orphan handling:** Worker creates row on first encounter if missing:
```python
def ensure_processing_row(link_id):
    execute("""
        INSERT INTO link_processing (link_id) 
        VALUES (%s) 
        ON CONFLICT (link_id) DO NOTHING
    """, (link_id,))
```

### Phase 2: Remove Immediate API Calls

#### 2a. Remove from `ingest_link_async()` (scratchpad_api.py)

```python
# REMOVE this entire block:
def _ext_disc():
    import time
    time.sleep(2)
    fetch_and_save_external_discussions(link_id, url)
    check_reverse_lookup(url, link_id)
ext_thread = threading.Thread(target=_ext_disc, daemon=True)
ext_thread.start()
```

External lookups now ONLY happen through the worker queue.

#### 2b. Remove synchronous reverse lookup from POST /add (scratchpad_routes.py)

Current code (lines ~770-815) does synchronous API call:
```python
if "reddit.com" in domain and "/comments/" in url:
    resolved_url = resolve_reddit_url(url)  # ← REMOVE THIS
```

**Replace with:**
```python
if "reddit.com" in domain and "/comments/" in url:
    # Create link with discussion URL
    result = supabase.table('links').insert({
        'url': url,
        'source': 'discussion-submission',  # Indicates this is a discussion URL
        ...
    }).execute()
    link_id = result.data[0]['id']
    
    # Create processing row with reverse lookup pending
    supabase.table('link_processing').insert({
        'link_id': link_id,
        'reverse_lookup_status': 'pending',
        'reddit_status': 'pending',
        'hn_status': 'pending',
        'summary_status': 'pending',
    }).execute()
    
    return RedirectResponse(url=f"/link/{link_id}", status_code=303)
```

The worker will:
1. See `reverse_lookup_status = 'pending'` (high priority)
2. Resolve the Reddit/HN URL to the original article
3. Update `reverse_lookup_target_id` with the article's link_id
4. Mark original link as `source = 'discussion-ref'`
5. Detail page auto-redirects to the article

### Phase 3: Tick-Based Worker (Every 2 Seconds)

#### New worker loop structure:

```python
# backoff.py - Add HN rate limiting (already defined, just ensure it's used)
RATE_LIMITS = {
    'reddit': {'requests_per_minute': 30, 'window_seconds': 60},
    'hackernews': {'requests_per_minute': 30, 'window_seconds': 60},
    'anthropic': {'requests_per_minute': 50, 'window_seconds': 60},
}

# worker.py - New tick-based loop using link_processing table

def get_next_work_item():
    """
    Get highest priority item needing processing.
    Priority order:
    1. Reverse lookups (user waiting)
    2. Reddit lookups for user-submitted links
    3. HN lookups for user-submitted links
    4. Reddit/HN lookups for recent links
    5. Backlog
    """
    # First: pending reverse lookups (highest priority)
    item = query_one("""
        SELECT lp.link_id, l.url, 'reverse_lookup' as task_type
        FROM link_processing lp
        JOIN links l ON l.id = lp.link_id
        WHERE lp.reverse_lookup_status = 'pending'
        ORDER BY lp.created_at ASC
        LIMIT 1
    """)
    if item:
        return item
    
    # Second: Reddit lookups (prioritize user-submitted, then recent)
    item = query_one("""
        SELECT lp.link_id, l.url, 'reddit' as task_type
        FROM link_processing lp
        JOIN links l ON l.id = lp.link_id
        WHERE lp.reddit_status = 'pending'
          AND l.source NOT IN ('auto-parent', 'discussion-ref')
        ORDER BY 
            CASE WHEN l.source = 'agent' OR l.submitted_by NOT IN ('auto', 'gatherer', '') THEN 0 ELSE 1 END,
            CASE WHEN l.created_at > NOW() - INTERVAL '24 hours' THEN 0 ELSE 1 END,
            lp.created_at ASC
        LIMIT 1
    """)
    if item:
        return item
    
    # Third: HN lookups (same priority logic)
    item = query_one("""
        SELECT lp.link_id, l.url, 'hn' as task_type
        FROM link_processing lp
        JOIN links l ON l.id = lp.link_id
        WHERE lp.hn_status = 'pending'
          AND l.source NOT IN ('auto-parent', 'discussion-ref')
        ORDER BY 
            CASE WHEN l.source = 'agent' OR l.submitted_by NOT IN ('auto', 'gatherer', '') THEN 0 ELSE 1 END,
            CASE WHEN l.created_at > NOW() - INTERVAL '24 hours' THEN 0 ELSE 1 END,
            lp.created_at ASC
        LIMIT 1
    """)
    return item


async def process_work_item(item: dict):
    """Process a single work item (reverse lookup, Reddit, or HN)."""
    link_id = item['link_id']
    url = item['url']
    task_type = item['task_type']
    
    try:
        if task_type == 'reverse_lookup':
            await process_reverse_lookup(link_id, url)
        elif task_type == 'reddit':
            await process_reddit_lookup(link_id, url)
        elif task_type == 'hn':
            await process_hn_lookup(link_id, url)
    except Exception as e:
        # Record error
        error_col = f"{task_type}_error" if task_type != 'reverse_lookup' else 'reddit_error'
        status_col = f"{task_type}_status" if task_type != 'reverse_lookup' else 'reverse_lookup_status'
        execute(f"""
            UPDATE link_processing 
            SET {status_col} = 'failed', {error_col} = %s, updated_at = NOW()
            WHERE link_id = %s
        """, (str(e)[:500], link_id))


async def process_reverse_lookup(link_id: int, url: str):
    """Resolve Reddit/HN discussion URL to original article."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    original_url = None
    platform = None
    
    if "reddit.com" in domain:
        if not check_rate_limit("reddit"):
            return  # Rate limited, will retry next tick
        record_request("reddit")
        original_url = resolve_reddit_url(url)
        platform = "reddit"
    elif "news.ycombinator.com" in domain:
        if not check_rate_limit("hackernews"):
            return  # Rate limited, will retry next tick
        record_request("hackernews")
        original_url = resolve_hn_url(url)
        platform = "hackernews"
    
    if original_url:
        # Find or create the original article
        original_url = normalize_url(original_url)
        original_link_id = find_or_create_link(original_url)
        
        # Update processing record
        execute("""
            UPDATE link_processing 
            SET reverse_lookup_status = 'completed',
                reverse_lookup_target_id = %s,
                updated_at = NOW()
            WHERE link_id = %s
        """, (original_link_id, link_id))
        
        # Add discussion URL as external discussion for the article
        add_external_discussion(original_link_id, platform, url)
        
        # Mark original link as discussion-ref
        execute("""
            UPDATE links SET source = 'discussion-ref', parent_link_id = %s
            WHERE id = %s
        """, (original_link_id, link_id))
    else:
        # No original found (self-post or error)
        execute("""
            UPDATE link_processing 
            SET reverse_lookup_status = 'not_found', updated_at = NOW()
            WHERE link_id = %s
        """, (link_id,))
        execute("""
            UPDATE links SET source = 'discussion-ref' WHERE id = %s
        """, (link_id,))


async def process_reddit_lookup(link_id: int, url: str):
    """Search Reddit for discussions about this URL."""
    if not check_rate_limit("reddit"):
        return  # Rate limited, will retry next tick
    
    record_request("reddit")
    discussions = search_reddit_discussions(url)
    
    status = 'completed' if discussions else 'not_found'
    execute("""
        UPDATE link_processing 
        SET reddit_status = %s, reddit_checked_at = NOW(), updated_at = NOW()
        WHERE link_id = %s
    """, (status, link_id))
    
    if discussions:
        save_external_discussions(link_id, discussions)


async def process_hn_lookup(link_id: int, url: str):
    """Search HN for discussions about this URL."""
    if not check_rate_limit("hackernews"):
        return  # Rate limited, will retry next tick
    
    record_request("hackernews")
    discussions = search_hn_discussions(url)
    
    status = 'completed' if discussions else 'not_found'
    execute("""
        UPDATE link_processing 
        SET hn_status = %s, hn_checked_at = NOW(), updated_at = NOW()
        WHERE link_id = %s
    """, (status, link_id))
    
    if discussions:
        save_external_discussions(link_id, discussions)


# Main worker loop
async def _external_lookup_loop():
    """Tick every 2 seconds, process one item."""
    while _worker_running:
        try:
            item = get_next_work_item()
            if item:
                await process_work_item(item)
        except Exception as e:
            print(f"[Worker] External lookup error: {e}")
        
        await asyncio.sleep(2)  # 30 items/min capacity per API
```

### Phase 4: Link Detail Page — Handle Processing States

**API endpoint for status polling:**

```python
@router.get("/api/link/{link_id}/processing")
async def get_link_processing_status(link_id: int):
    """Get processing status for a link (for live-loading UI)."""
    proc = query_one("""
        SELECT 
            reddit_status, reddit_checked_at,
            hn_status, hn_checked_at,
            summary_status, summary_generated_at,
            reverse_lookup_status, reverse_lookup_target_id
        FROM link_processing
        WHERE link_id = %s
    """, (link_id,))
    
    if not proc:
        return {"status": "not_found"}
    
    return {
        "reddit": {"status": proc["reddit_status"], "checked_at": proc["reddit_checked_at"]},
        "hn": {"status": proc["hn_status"], "checked_at": proc["hn_checked_at"]},
        "summary": {"status": proc["summary_status"], "generated_at": proc["summary_generated_at"]},
        "reverse_lookup": {
            "status": proc["reverse_lookup_status"],
            "target_id": proc["reverse_lookup_target_id"]
        }
    }
```

**Link detail page JS:**

```javascript
// Poll processing status for pending items
function pollProcessingStatus(linkId) {
    fetch('/api/link/' + linkId + '/processing')
        .then(r => r.json())
        .then(data => {
            // Handle reverse lookup redirect
            if (data.reverse_lookup?.status === 'completed' && data.reverse_lookup?.target_id) {
                window.location.href = '/link/' + data.reverse_lookup.target_id;
                return;
            }
            
            // Update UI indicators
            updateDiscussionStatus(data.reddit, data.hn);
            updateSummaryStatus(data.summary);
            
            // Keep polling if anything is pending
            if (data.reddit?.status === 'pending' || 
                data.hn?.status === 'pending' || 
                data.summary?.status === 'pending' ||
                data.reverse_lookup?.status === 'pending') {
                setTimeout(() => pollProcessingStatus(linkId), 2000);
            }
        });
}

// Start polling on page load if link has pending tasks
if (PROCESSING_PENDING) {
    pollProcessingStatus(LINK_ID);
}
```

**UI States:**
- `pending` → Show spinner + "Checking Reddit/HN..."
- `completed` → Show results (or "No discussions found")
- `not_found` → Show "No discussions found on Reddit/HN"
- `failed` → Show "Error checking" (with retry button)

**Reverse lookup redirect:** When `reverse_lookup_target_id` is set, auto-redirect to the original article.

---

## Rate Limiting Strategy: Even Ticks

**Every 2 seconds:**
1. Check if there's work in the queue
2. Process ONE item (either reverse lookup OR discussion search)
3. Each API call uses one slot from that API's rate limit

**Rate Budget:**
- Reddit: 30/min = 1 every 2 seconds
- HN: 30/min = 1 every 2 seconds
- Combined: 60 API calls/min max

**Why even ticks over free-firing:**
- Predictable traffic pattern (Reddit likes this)
- No bursts that could trigger stricter limits
- Simple to reason about and debug
- Priority queue ensures urgent items processed first

---

## Files to Change

| File | Changes |
|------|---------|
| **DB** | Create `link_processing` table with per-task status/timestamps |
| `backoff.py` | Ensure `hackernews` rate limit is enforced (already defined) |
| `scratchpad_api.py` | Remove `_ext_disc` thread from `ingest_link_async()` |
| `scratchpad_api.py` | Add `ensure_processing_row()` helper |
| `scratchpad_api.py` | Add `/api/link/{id}/processing` endpoint |
| `scratchpad_routes.py` | Remove sync reverse lookup from POST /add |
| `scratchpad_routes.py` | Create `link_processing` row on link creation |
| `scratchpad_routes.py` | Add processing status polling JS to detail page |
| `worker.py` | Refactor to use `link_processing` table |
| `worker.py` | Add tick-based `_external_lookup_loop()` |
| `worker.py` | Separate Reddit/HN/Summary processing functions |

---

## Migration Path

1. **Run DB migration** — create `link_processing` table
2. **Backfill existing links:**
   ```sql
   -- Create processing rows for all existing links
   INSERT INTO link_processing (link_id, reddit_status, hn_status, summary_status)
   SELECT id, 'pending', 'pending', 
          CASE WHEN summary IS NOT NULL AND summary != '' THEN 'completed' ELSE 'pending' END
   FROM links
   WHERE source NOT IN ('auto-parent', 'discussion-ref')
   ON CONFLICT (link_id) DO NOTHING;
   
   -- Mark links that already have external discussions as completed
   UPDATE link_processing lp
   SET reddit_status = 'completed', reddit_checked_at = NOW()
   WHERE EXISTS (
       SELECT 1 FROM external_discussions ed 
       WHERE ed.link_id = lp.link_id AND ed.platform = 'reddit'
   );
   
   UPDATE link_processing lp
   SET hn_status = 'completed', hn_checked_at = NOW()
   WHERE EXISTS (
       SELECT 1 FROM external_discussions ed 
       WHERE ed.link_id = lp.link_id AND ed.platform = 'hackernews'
   );
   ```
3. **Deploy code changes**
4. **Worker will process** remaining `pending` items in priority order

---

## Open Questions Resolved

| Question | Decision |
|----------|----------|
| Shared vs separate timers? | **Separate** — 30/min Reddit, 30/min HN |
| Queue persistence? | **Use existing DB** — query for `external_lookup_at IS NULL` |
| User submits Reddit link? | **Create immediately** with `source='pending-reverse-lookup'`, resolve via queue |
| Reserve rate for reverse lookup? | **No** — use priority queue instead (reverse lookups = priority 0) |

---

## Testing Checklist

- [ ] Submit normal link → `link_processing` row created with `pending` statuses
- [ ] Worker processes Reddit lookup → status changes to `completed` or `not_found`
- [ ] Worker processes HN lookup → status changes to `completed` or `not_found`
- [ ] Submit Reddit discussion URL → reverse lookup queued, resolves within ~4 seconds
- [ ] Submit HN discussion URL → same as Reddit
- [ ] Reverse lookup completes → detail page auto-redirects to original article
- [ ] Rate limit reached → worker skips that API, processes other tasks
- [ ] Worker restart → picks up where it left off (pending statuses remain)
- [ ] Link detail page → shows spinner for pending, results for completed
- [ ] Error handling → failed status set, error message stored

---

## Summary of Changes from Previous Plan

| Previous | Updated |
|----------|---------|
| Add `external_lookup_at` column to `links` | Create separate `link_processing` table |
| One timestamp for all external lookups | Per-task status + timestamp (Reddit, HN, Summary) |
| `source = 'pending-reverse-lookup'` | `reverse_lookup_status = 'pending'` in processing table |
| Mixed concerns in `links` table | Clean separation: content vs processing state |

**Benefits:**
- `links` table stays thin and fast for feed queries
- Worker updates don't create dead tuples in main table
- Easy to see exactly what's pending/completed/failed per task
- Future-proof: easy to add more processing tasks (screenshots, embeddings, etc.)

---

*Ready for implementation. Proceed?*
