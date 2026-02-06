"""
Background Worker for Link Processing

NEW ARCHITECTURE (2025-01):
- Uses link_processing table for per-task status tracking
- Tick-based loop (every 2 seconds) processes ONE item per tick
- Priority queue: reverse lookups → user-submitted → recent → backlog
- Respects rate limits (30/min Reddit, 30/min HN)

Handles:
- Reddit discussion lookup
- HN discussion lookup  
- AI summarization (with budget constraints)
- Reverse URL lookup (Reddit/HN discussion URL → original article)

Budget constraint: $50/month max for Anthropic API
"""

import os
import asyncio
import httpx
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from uuid import uuid4

from db import query, query_one, execute
from psycopg2.extras import Json
from backoff import (
    check_backoff, record_success, record_failure, get_backoff_status,
    check_rate_and_backoff, record_request, check_rate_limit, get_rate_limit_status
)

# ============================================================
# Configuration
# ============================================================

MONTHLY_BUDGET_USD = 50.0
TICK_INTERVAL_SECONDS = 2  # Process one item every 2 seconds

# Claude Sonnet pricing per 1M tokens
SONNET_MODEL = "claude-3-5-sonnet-20241022"
SONNET_INPUT_PRICE = 3.0   # $3 per 1M input tokens
SONNET_OUTPUT_PRICE = 15.0  # $15 per 1M output tokens

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


# ============================================================
# Helper: Ensure processing row exists
# ============================================================

def ensure_processing_row(link_id: int, priority: int = 5) -> None:
    """Create a link_processing row if it doesn't exist."""
    execute(
        """
        INSERT INTO link_processing (link_id, priority) 
        VALUES (%s, %s) 
        ON CONFLICT (link_id) DO NOTHING
        """,
        (link_id, priority)
    )


# ============================================================
# Budget Tracking
# ============================================================

def get_monthly_ai_spend() -> float:
    """Query ai_token_usage for current month's total_cost_usd."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    row = query_one(
        """
        SELECT COALESCE(SUM(estimated_cost_usd), 0) as total_cost
        FROM ai_token_usage
        WHERE created_at >= %s
        """,
        (month_start,)
    )
    
    return float(row["total_cost"]) if row else 0.0


def check_budget_ok(limit: float = MONTHLY_BUDGET_USD) -> bool:
    """Return True if monthly spend < limit."""
    spent = get_monthly_ai_spend()
    return spent < limit


# ============================================================
# AI Summary Generation
# ============================================================

def _record_token_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    estimated_cost: float,
    operation_type: str,
    link_id: int
):
    """Record token usage to ai_token_usage table."""
    try:
        execute(
            """
            INSERT INTO ai_token_usage 
            (model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, operation_type, link_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (model, input_tokens, output_tokens, input_tokens + output_tokens,
             estimated_cost, operation_type, link_id)
        )
    except Exception as e:
        print(f"[Worker] Token usage tracking failed: {e}")


async def generate_summary(link: dict) -> Optional[str]:
    """
    Use Claude Sonnet to generate a summary.
    
    Input: link dict with title, description, content
    Output: 2-3 sentence summary, or None on failure
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[Worker] ANTHROPIC_API_KEY not set, skipping summary")
        return None
    
    link_id = link.get("id")
    title = link.get("title") or ""
    description = link.get("description") or ""
    content = link.get("content") or ""
    url = link.get("url") or ""
    
    # Build input text - prefer content, fall back to description
    text_to_summarize = content[:3000] if content else description[:1000]
    
    if not title and not text_to_summarize:
        print(f"[Worker] Link {link_id} has no content to summarize")
        return None
    
    prompt = f"""Generate a 2-3 sentence summary for this link.

Title: {title}
URL: {url}
Content: {text_to_summarize}

Write a concise, informative summary that captures the key points. 
Focus on what makes this interesting or notable.
Just output the summary, no preamble."""

    payload = {
        "model": SONNET_MODEL,
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}],
    }
    
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(ANTHROPIC_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            
            # Extract text
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            
            # Extract usage
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            
            # Calculate cost
            cost = (input_tokens * SONNET_INPUT_PRICE + output_tokens * SONNET_OUTPUT_PRICE) / 1_000_000
            
            # Record usage
            _record_token_usage(
                model=SONNET_MODEL,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=cost,
                operation_type="summary",
                link_id=link_id
            )
            
            summary = text.strip()
            if summary and len(summary) > 20:
                record_success("anthropic")
                return summary
            
            return None
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            print(f"[Worker] Anthropic API error for link {link_id}: {error_msg}")
            record_failure("anthropic", error_msg)
            return None
        except Exception as e:
            error_msg = str(e)
            print(f"[Worker] Summary generation failed for link {link_id}: {error_msg}")
            record_failure("anthropic", error_msg)
            return None


# ============================================================
# Priority Queue: Get Next Work Item
# ============================================================

def get_next_work_item() -> Optional[Dict[str, Any]]:
    """
    Get highest priority item needing processing.
    
    Priority order:
    1. Reverse lookups (user waiting for redirect)
    2. Reddit lookups for user-submitted links (high priority)
    3. HN lookups for user-submitted links
    4. Reddit lookups for recent links
    5. HN lookups for recent links
    6. Backlog
    
    Returns dict with: link_id, url, task_type
    """
    # 1. Pending reverse lookups (highest priority - user is waiting)
    item = query_one("""
        SELECT lp.link_id, l.url, 'reverse_lookup' as task_type
        FROM link_processing lp
        JOIN links l ON l.id = lp.link_id
        WHERE lp.reverse_lookup_status = 'pending'
        ORDER BY lp.created_at ASC
        LIMIT 1
    """)
    if item:
        return dict(item)
    
    # 2. Reddit lookups (prioritize high-priority, then by age)
    # Check rate limit first
    if check_rate_limit("reddit") and check_backoff("reddit"):
        item = query_one("""
            SELECT lp.link_id, l.url, 'reddit' as task_type
            FROM link_processing lp
            JOIN links l ON l.id = lp.link_id
            WHERE lp.reddit_status = 'pending'
            ORDER BY lp.priority DESC, lp.created_at ASC
            LIMIT 1
        """)
        if item:
            return dict(item)
    
    # 3. HN lookups
    if check_rate_limit("hackernews") and check_backoff("hackernews"):
        item = query_one("""
            SELECT lp.link_id, l.url, 'hn' as task_type
            FROM link_processing lp
            JOIN links l ON l.id = lp.link_id
            WHERE lp.hn_status = 'pending'
            ORDER BY lp.priority DESC, lp.created_at ASC
            LIMIT 1
        """)
        if item:
            return dict(item)
    
    # NOTE: Summary generation is NOT handled by the worker yet
    # summary_status column exists for future use, but summaries remain manual for now
    
    return None


# ============================================================
# Process Individual Work Items
# ============================================================

async def process_reverse_lookup(link_id: int, url: str) -> bool:
    """
    Resolve Reddit/HN discussion URL to original article.
    Returns True if successful, False if should retry later.
    """
    from urllib.parse import urlparse
    from scratchpad_api import resolve_reddit_url, resolve_hn_url, normalize_url
    
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    original_url = None
    platform = None
    
    if "reddit.com" in domain:
        if not check_rate_limit("reddit"):
            return False  # Rate limited, will retry next tick
        record_request("reddit")
        try:
            original_url = resolve_reddit_url(url)
            platform = "reddit"
        except Exception as e:
            print(f"[Worker] Reddit resolve error for {link_id}: {e}")
            execute("""
                UPDATE link_processing 
                SET reverse_lookup_status = 'failed', reddit_error = %s, updated_at = NOW()
                WHERE link_id = %s
            """, (str(e)[:500], link_id))
            return True  # Don't retry on error
            
    elif "news.ycombinator.com" in domain:
        if not check_rate_limit("hackernews"):
            return False  # Rate limited, will retry next tick
        record_request("hackernews")
        try:
            original_url = resolve_hn_url(url)
            platform = "hackernews"
        except Exception as e:
            print(f"[Worker] HN resolve error for {link_id}: {e}")
            execute("""
                UPDATE link_processing 
                SET reverse_lookup_status = 'failed', hn_error = %s, updated_at = NOW()
                WHERE link_id = %s
            """, (str(e)[:500], link_id))
            return True
    else:
        # Not a discussion URL
        execute("""
            UPDATE link_processing 
            SET reverse_lookup_status = 'skipped', updated_at = NOW()
            WHERE link_id = %s
        """, (link_id,))
        return True
    
    if original_url:
        # Normalize and find/create the original article
        original_url = normalize_url(original_url)
        
        # Check if original already exists
        existing = query_one(
            "SELECT id FROM links WHERE url = %s",
            (original_url,)
        )
        
        if existing:
            original_link_id = existing["id"]
        else:
            # Create the original article
            result = execute("""
                INSERT INTO links (url, source, submitted_by, processing_status, processing_priority)
                VALUES (%s, 'reverse-lookup', 'worker', 'new', 5)
                RETURNING id
            """, (original_url,))
            original_link_id = result[0]["id"] if result else None
            
            if original_link_id:
                # Create processing row for the new link
                ensure_processing_row(original_link_id, priority=5)
        
        if original_link_id:
            # Update processing record
            execute("""
                UPDATE link_processing 
                SET reverse_lookup_status = 'completed',
                    reverse_lookup_target_id = %s,
                    updated_at = NOW()
                WHERE link_id = %s
            """, (original_link_id, link_id))
            
            # Add discussion URL as external discussion for the article
            import re
            external_id = None
            if platform == "reddit":
                match = re.search(r'/comments/([a-z0-9]+)', url)
                external_id = match.group(1) if match else f"manual-{link_id}"
            elif platform == "hackernews":
                match = re.search(r'id=(\d+)', url)
                external_id = match.group(1) if match else f"manual-{link_id}"
            
            try:
                execute("""
                    INSERT INTO external_discussions 
                    (link_id, platform, external_url, external_id, title, score, num_comments)
                    VALUES (%s, %s, %s, %s, '', 0, 0)
                    ON CONFLICT (link_id, platform, external_id) DO NOTHING
                """, (original_link_id, platform, url, external_id))
            except Exception as e:
                print(f"[Worker] Error adding external discussion: {e}")
            
            # Mark original discussion link as discussion-ref
            execute("""
                UPDATE links 
                SET source = 'discussion-ref', parent_link_id = %s
                WHERE id = %s
            """, (original_link_id, link_id))
            
            print(f"[Worker] Resolved {platform} discussion {link_id} → article {original_link_id}")
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
        print(f"[Worker] Reverse lookup found no original for {link_id}")
    
    return True


async def process_reddit_lookup(link_id: int, url: str) -> bool:
    """Search Reddit for discussions about this URL."""
    from scratchpad_api import find_external_discussions, save_external_discussions
    
    if not check_rate_limit("reddit"):
        return False  # Rate limited, will retry next tick
    
    record_request("reddit")
    
    try:
        # Use find_external_discussions which handles both Reddit and HN
        # We'll filter for Reddit only
        all_discussions = find_external_discussions(url)
        reddit_discussions = [d for d in all_discussions if d.get("platform") == "reddit"]
        
        if reddit_discussions:
            save_external_discussions(link_id, reddit_discussions)
            status = 'completed'
        else:
            status = 'not_found'
        
        execute("""
            UPDATE link_processing 
            SET reddit_status = %s, reddit_checked_at = NOW(), updated_at = NOW()
            WHERE link_id = %s
        """, (status, link_id))
        
        record_success("reddit")
        print(f"[Worker] Reddit lookup for {link_id}: {status} ({len(reddit_discussions)} found)")
        return True
        
    except Exception as e:
        error_msg = str(e)[:500]
        print(f"[Worker] Reddit lookup error for {link_id}: {e}")
        execute("""
            UPDATE link_processing 
            SET reddit_status = 'failed', reddit_error = %s, updated_at = NOW()
            WHERE link_id = %s
        """, (error_msg, link_id))
        record_failure("reddit", error_msg)
        return True


async def process_hn_lookup(link_id: int, url: str) -> bool:
    """Search HN for discussions about this URL."""
    from scratchpad_api import find_external_discussions, save_external_discussions
    
    if not check_rate_limit("hackernews"):
        return False  # Rate limited, will retry next tick
    
    record_request("hackernews")
    
    try:
        # Use find_external_discussions and filter for HN
        all_discussions = find_external_discussions(url)
        hn_discussions = [d for d in all_discussions if d.get("platform") == "hackernews"]
        
        if hn_discussions:
            save_external_discussions(link_id, hn_discussions)
            status = 'completed'
        else:
            status = 'not_found'
        
        execute("""
            UPDATE link_processing 
            SET hn_status = %s, hn_checked_at = NOW(), updated_at = NOW()
            WHERE link_id = %s
        """, (status, link_id))
        
        record_success("hackernews")
        print(f"[Worker] HN lookup for {link_id}: {status} ({len(hn_discussions)} found)")
        return True
        
    except Exception as e:
        error_msg = str(e)[:500]
        print(f"[Worker] HN lookup error for {link_id}: {e}")
        execute("""
            UPDATE link_processing 
            SET hn_status = 'failed', hn_error = %s, updated_at = NOW()
            WHERE link_id = %s
        """, (error_msg, link_id))
        record_failure("hackernews", error_msg)
        return True


async def process_work_item(item: Dict[str, Any]) -> bool:
    """
    Process a single work item.
    Returns True if completed, False if should retry later.
    """
    link_id = item["link_id"]
    url = item.get("url", "")
    task_type = item["task_type"]
    
    try:
        if task_type == "reverse_lookup":
            return await process_reverse_lookup(link_id, url)
        elif task_type == "reddit":
            return await process_reddit_lookup(link_id, url)
        elif task_type == "hn":
            return await process_hn_lookup(link_id, url)
        # NOTE: summary task_type is not processed yet - summaries remain manual
        else:
            print(f"[Worker] Unknown task type: {task_type}")
            return True
            
    except Exception as e:
        print(f"[Worker] Error processing {task_type} for {link_id}: {e}")
        return True  # Don't retry on unexpected errors


# ============================================================
# Worker Status
# ============================================================

def get_worker_status() -> dict:
    """Get current worker status for admin display."""
    # Queue stats from link_processing
    queue_stats = query_one("""
        SELECT 
            SUM(CASE WHEN reddit_status = 'pending' THEN 1 ELSE 0 END) as reddit_pending,
            SUM(CASE WHEN hn_status = 'pending' THEN 1 ELSE 0 END) as hn_pending,
            SUM(CASE WHEN summary_status = 'pending' THEN 1 ELSE 0 END) as summary_pending,
            SUM(CASE WHEN reverse_lookup_status = 'pending' THEN 1 ELSE 0 END) as reverse_pending,
            SUM(CASE WHEN reddit_status = 'completed' THEN 1 ELSE 0 END) as reddit_completed,
            SUM(CASE WHEN hn_status = 'completed' THEN 1 ELSE 0 END) as hn_completed,
            SUM(CASE WHEN summary_status = 'completed' THEN 1 ELSE 0 END) as summary_completed,
            SUM(CASE WHEN reddit_status = 'failed' THEN 1 ELSE 0 END) as reddit_failed,
            SUM(CASE WHEN hn_status = 'failed' THEN 1 ELSE 0 END) as hn_failed,
            SUM(CASE WHEN summary_status = 'failed' THEN 1 ELSE 0 END) as summary_failed,
            COUNT(*) as total
        FROM link_processing
    """)
    
    # Monthly spend
    monthly_spend = get_monthly_ai_spend()
    budget_remaining = max(0, MONTHLY_BUDGET_USD - monthly_spend)
    
    # Backoff states
    anthropic_backoff = get_backoff_status("anthropic")
    reddit_backoff = get_backoff_status("reddit")
    hackernews_backoff = get_backoff_status("hackernews")
    
    # Rate limit states
    reddit_rate = get_rate_limit_status("reddit")
    hackernews_rate = get_rate_limit_status("hackernews")
    anthropic_rate = get_rate_limit_status("anthropic")
    
    # Recent job runs
    recent_jobs = query("""
        SELECT job_type, status, started_at, completed_at, items_processed, errors
        FROM job_runs
        ORDER BY started_at DESC
        LIMIT 5
    """)
    
    return {
        "queue": {
            "reddit_pending": queue_stats["reddit_pending"] or 0,
            "hn_pending": queue_stats["hn_pending"] or 0,
            "summary_pending": queue_stats["summary_pending"] or 0,
            "reverse_pending": queue_stats["reverse_pending"] or 0,
            "reddit_completed": queue_stats["reddit_completed"] or 0,
            "hn_completed": queue_stats["hn_completed"] or 0,
            "summary_completed": queue_stats["summary_completed"] or 0,
            "reddit_failed": queue_stats["reddit_failed"] or 0,
            "hn_failed": queue_stats["hn_failed"] or 0,
            "summary_failed": queue_stats["summary_failed"] or 0,
            "total": queue_stats["total"] or 0,
        },
        "budget": {
            "monthly_spend_usd": round(monthly_spend, 4),
            "budget_limit_usd": MONTHLY_BUDGET_USD,
            "budget_remaining_usd": round(budget_remaining, 4),
            "budget_ok": monthly_spend < MONTHLY_BUDGET_USD,
        },
        "backoff_states": {
            "anthropic": anthropic_backoff,
            "reddit": reddit_backoff,
            "hackernews": hackernews_backoff,
        },
        "rate_limit_states": {
            "reddit": reddit_rate,
            "hackernews": hackernews_rate,
            "anthropic": anthropic_rate,
        },
        "recent_jobs": recent_jobs,
        "worker_running": _worker_running,
        "tick_interval_seconds": TICK_INTERVAL_SECONDS,
    }


def get_queue_summary() -> dict:
    """Get a compact queue summary for display."""
    stats = query_one("""
        SELECT 
            SUM(CASE WHEN reddit_status = 'pending' THEN 1 ELSE 0 END) as reddit_pending,
            SUM(CASE WHEN hn_status = 'pending' THEN 1 ELSE 0 END) as hn_pending,
            SUM(CASE WHEN summary_status = 'pending' THEN 1 ELSE 0 END) as summary_pending,
            SUM(CASE WHEN reverse_lookup_status = 'pending' THEN 1 ELSE 0 END) as reverse_pending
        FROM link_processing
    """)
    
    return {
        "reddit": stats["reddit_pending"] or 0,
        "hn": stats["hn_pending"] or 0,
        "summary": stats["summary_pending"] or 0,
        "reverse": stats["reverse_pending"] or 0,
        "total": (stats["reddit_pending"] or 0) + (stats["hn_pending"] or 0) + 
                 (stats["summary_pending"] or 0) + (stats["reverse_pending"] or 0),
    }


# ============================================================
# Background Task Runner (Tick-Based)
# ============================================================

_worker_task: Optional[asyncio.Task] = None
_worker_running = False


async def _tick_loop():
    """
    Tick-based worker loop.
    Every TICK_INTERVAL_SECONDS, process ONE work item.
    This gives us even, predictable API traffic.
    """
    global _worker_running
    print(f"[Worker] Tick-based loop started (interval: {TICK_INTERVAL_SECONDS}s)")
    
    items_processed = 0
    last_log_time = datetime.now(timezone.utc)
    
    while _worker_running:
        try:
            item = get_next_work_item()
            if item:
                completed = await process_work_item(item)
                if completed:
                    items_processed += 1
            
            # Log progress every 60 seconds
            now = datetime.now(timezone.utc)
            if (now - last_log_time).total_seconds() >= 60:
                queue = get_queue_summary()
                print(f"[Worker] Progress: {items_processed} items processed. Queue: R:{queue['reddit']} HN:{queue['hn']} Sum:{queue['summary']} Rev:{queue['reverse']}")
                last_log_time = now
                items_processed = 0
                
        except Exception as e:
            print(f"[Worker] Tick error: {e}")
        
        await asyncio.sleep(TICK_INTERVAL_SECONDS)
    
    print("[Worker] Tick-based loop stopped")


def start_background_worker():
    """Start the background worker task."""
    global _worker_task, _worker_running
    
    if _worker_running:
        print("[Worker] Already running")
        return
    
    _worker_running = True
    _worker_task = asyncio.create_task(_tick_loop())
    print("[Worker] Background worker started")


def stop_background_worker():
    """Stop the background worker task."""
    global _worker_task, _worker_running
    
    _worker_running = False
    if _worker_task:
        _worker_task.cancel()
        _worker_task = None
    print("[Worker] Background worker stopped")


def is_worker_running() -> bool:
    """Check if the background worker is running."""
    return _worker_running


# ============================================================
# Admin Actions
# ============================================================

def retry_failed_items(task_type: str = None) -> int:
    """
    Reset failed items back to pending for retry.
    
    Args:
        task_type: 'reddit', 'hn', 'summary', or None for all
    
    Returns count of items reset.
    """
    count = 0
    
    if task_type is None or task_type == 'reddit':
        result = execute("""
            UPDATE link_processing 
            SET reddit_status = 'pending', reddit_error = NULL
            WHERE reddit_status = 'failed'
        """)
        count += len(result) if result else 0
    
    if task_type is None or task_type == 'hn':
        result = execute("""
            UPDATE link_processing 
            SET hn_status = 'pending', hn_error = NULL
            WHERE hn_status = 'failed'
        """)
        count += len(result) if result else 0
    
    if task_type is None or task_type == 'summary':
        result = execute("""
            UPDATE link_processing 
            SET summary_status = 'pending', summary_error = NULL
            WHERE summary_status = 'failed'
        """)
        count += len(result) if result else 0
    
    print(f"[Worker] Reset {count} failed items to pending (type: {task_type or 'all'})")
    return count


def get_failed_items(limit: int = 20) -> list:
    """Get recently failed items with their errors."""
    return query("""
        SELECT 
            lp.link_id,
            l.url,
            l.title,
            lp.reddit_status,
            lp.reddit_error,
            lp.hn_status,
            lp.hn_error,
            lp.summary_status,
            lp.summary_error,
            lp.updated_at
        FROM link_processing lp
        JOIN links l ON l.id = lp.link_id
        WHERE lp.reddit_status = 'failed' 
           OR lp.hn_status = 'failed' 
           OR lp.summary_status = 'failed'
        ORDER BY lp.updated_at DESC
        LIMIT %s
    """, (limit,))


# ============================================================
# Legacy Compatibility
# ============================================================

async def run_processing_batch(batch_size: int = 20) -> dict:
    """
    Legacy batch processing function.
    Now just runs tick-loop items synchronously.
    Kept for compatibility with existing admin triggers.
    """
    processed = 0
    for _ in range(batch_size):
        item = get_next_work_item()
        if not item:
            break
        completed = await process_work_item(item)
        if completed:
            processed += 1
    
    return {
        "processed": processed,
        "monthly_spend": get_monthly_ai_spend(),
        "budget_ok": check_budget_ok(),
    }
