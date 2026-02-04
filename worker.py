"""
Background Worker for Link Processing

Handles:
- AI summarization (with budget constraints)
- Reddit/HN reverse lookup for external discussions
- Processing queue management

Budget constraint: $50/month max for Anthropic API
"""

import os
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import uuid4

from db import query, query_one, execute
from backoff import (
    check_backoff, record_success, record_failure, get_backoff_status,
    check_rate_and_backoff, record_request, get_rate_limit_status
)

# ============================================================
# Configuration
# ============================================================

MONTHLY_BUDGET_USD = 50.0

# Claude Sonnet pricing per 1M tokens
SONNET_MODEL = "claude-3-5-sonnet-20241022"
SONNET_INPUT_PRICE = 3.0   # $3 per 1M input tokens
SONNET_OUTPUT_PRICE = 15.0  # $15 per 1M output tokens

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


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


async def get_monthly_ai_spend_async() -> float:
    """Async wrapper for get_monthly_ai_spend."""
    return get_monthly_ai_spend()


async def check_budget_ok_async(limit: float = MONTHLY_BUDGET_USD) -> bool:
    """Async wrapper for check_budget_ok."""
    return check_budget_ok(limit)


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
    
    Tracks tokens in ai_token_usage table.
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
    
    # Build prompt
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
# External Discussion Discovery
# ============================================================

async def run_external_discussion_lookup(link_id: int, url: str):
    """
    Run Reddit/HN reverse lookup for a link.
    Uses existing functions from scratchpad_api but with backoff + rate limit checking.
    """
    from scratchpad_api import fetch_and_save_external_discussions, check_reverse_lookup
    
    # Check both backoff AND rate limit for reddit
    if not check_rate_and_backoff("reddit"):
        print(f"[Worker] Skipping Reddit lookup for {link_id} - in backoff or rate limited")
        return
    
    try:
        # Run the existing external discussion fetch
        fetch_and_save_external_discussions(link_id, url)
        
        # Check reverse lookup (if this is an HN/Reddit link)
        check_reverse_lookup(url, link_id)
        
        record_success("reddit")
    except Exception as e:
        error_msg = str(e)
        print(f"[Worker] External discussion lookup failed for link {link_id}: {error_msg}")
        record_failure("reddit", error_msg)


# ============================================================
# Job Logging
# ============================================================

def _log_job_start(job_type: str, metadata: dict = None) -> str:
    """Create a job_runs entry, return job_id."""
    job_id = str(uuid4())
    execute(
        """
        INSERT INTO job_runs (id, job_type, status, metadata)
        VALUES (%s, %s, 'running', %s)
        """,
        (job_id, job_type, metadata or {})
    )
    return job_id


def _log_job_complete(job_id: str, items_processed: int, error: str = None):
    """Mark a job as completed or failed."""
    status = "failed" if error else "completed"
    execute(
        """
        UPDATE job_runs 
        SET status = %s, completed_at = now(), items_processed = %s, error_message = %s
        WHERE id = %s
        """,
        (status, items_processed, error[:500] if error else None, job_id)
    )


# ============================================================
# Main Worker Function
# ============================================================

async def run_processing_batch(batch_size: int = 20) -> dict:
    """
    Main worker function - processes a batch of links.
    
    1. Check monthly budget (query ai_token_usage for current month)
       - If >= $50, log and skip AI steps
    
    2. Get batch of links:
       SELECT * FROM links 
       WHERE processing_status = 'new'
       ORDER BY processing_priority DESC, created_at ASC
       LIMIT batch_size
    
    3. For each link:
       a. Set processing_status = 'processing'
       b. If budget OK and no summary:
          - Check backoff for 'anthropic'
          - If OK: Generate summary with Sonnet
          - Record token usage
          - Handle failure with backoff.record_failure()
       c. If no external discussions found:
          - Check backoff for 'reddit'  
          - If OK: Run Reddit reverse lookup
          - Handle failure with backoff
       d. Set processing_status = 'completed', last_processed_at = now()
    
    4. Log job_run with items_processed count
    
    Returns dict with processing results.
    """
    job_id = _log_job_start("process_batch", {"batch_size": batch_size})
    
    try:
        # 1. Check monthly budget
        monthly_spend = get_monthly_ai_spend()
        budget_ok = monthly_spend < MONTHLY_BUDGET_USD
        
        if not budget_ok:
            print(f"[Worker] Monthly budget exceeded (${monthly_spend:.2f}/${MONTHLY_BUDGET_USD}), skipping AI processing")
        
        # 2. Get batch of links
        links = query(
            """
            SELECT id, url, title, description, content, summary, processing_status
            FROM links
            WHERE processing_status = 'new'
            ORDER BY processing_priority DESC, created_at ASC
            LIMIT %s
            """,
            (batch_size,)
        )
        
        if not links:
            print("[Worker] No links to process")
            _log_job_complete(job_id, 0)
            return {
                "processed": 0,
                "summaries_generated": 0,
                "discussions_found": 0,
                "monthly_spend": monthly_spend,
                "budget_ok": budget_ok,
            }
        
        print(f"[Worker] Processing batch of {len(links)} links")
        
        summaries_generated = 0
        discussions_checked = 0
        errors = []
        
        # 3. Process each link
        for link in links:
            link_id = link["id"]
            url = link.get("url", "")
            
            try:
                # a. Set processing_status = 'processing'
                execute(
                    "UPDATE links SET processing_status = 'processing' WHERE id = %s",
                    (link_id,)
                )
                
                # b. Generate summary if budget OK and no existing summary
                if budget_ok and not link.get("summary"):
                    if check_backoff("anthropic"):
                        summary = await generate_summary(link)
                        if summary:
                            execute(
                                "UPDATE links SET summary = %s WHERE id = %s",
                                (summary, link_id)
                            )
                            summaries_generated += 1
                            print(f"[Worker] Generated summary for link {link_id}")
                    else:
                        print(f"[Worker] Skipping summary for link {link_id} - anthropic in backoff")
                
                # c. Check for external discussions
                # First check if we already have discussions for this link
                existing_disc = query_one(
                    "SELECT id FROM external_discussions WHERE link_id = %s LIMIT 1",
                    (link_id,)
                )
                
                if not existing_disc and url:
                    await run_external_discussion_lookup(link_id, url)
                    discussions_checked += 1
                
                # d. Set processing_status = 'completed'
                execute(
                    """
                    UPDATE links 
                    SET processing_status = 'completed', last_processed_at = now()
                    WHERE id = %s
                    """,
                    (link_id,)
                )
                
            except Exception as e:
                error_msg = f"Link {link_id}: {str(e)}"
                errors.append(error_msg)
                print(f"[Worker] Error processing link {link_id}: {e}")
                
                # Mark as failed
                execute(
                    """
                    UPDATE links 
                    SET processing_status = 'failed', last_processed_at = now()
                    WHERE id = %s
                    """,
                    (link_id,)
                )
        
        # 4. Log job completion
        _log_job_complete(job_id, len(links), "; ".join(errors) if errors else None)
        
        result = {
            "processed": len(links),
            "summaries_generated": summaries_generated,
            "discussions_checked": discussions_checked,
            "errors": len(errors),
            "monthly_spend": monthly_spend,
            "budget_ok": budget_ok,
        }
        
        print(f"[Worker] Batch complete: {result}")
        return result
        
    except Exception as e:
        error_msg = str(e)
        print(f"[Worker] Batch processing failed: {error_msg}")
        _log_job_complete(job_id, 0, error_msg)
        return {
            "processed": 0,
            "error": error_msg,
        }


# ============================================================
# Worker Status
# ============================================================

def get_worker_status() -> dict:
    """Get current worker status for admin display."""
    # Queue size
    queue = query_one(
        "SELECT COUNT(*) as count FROM links WHERE processing_status = 'new'"
    )
    queue_size = queue["count"] if queue else 0
    
    # Processing count
    processing = query_one(
        "SELECT COUNT(*) as count FROM links WHERE processing_status = 'processing'"
    )
    processing_count = processing["count"] if processing else 0
    
    # Monthly spend
    monthly_spend = get_monthly_ai_spend()
    
    # Budget status
    budget_remaining = max(0, MONTHLY_BUDGET_USD - monthly_spend)
    
    # Backoff states (exponential backoff from failures)
    anthropic_backoff = get_backoff_status("anthropic")
    reddit_backoff = get_backoff_status("reddit")
    
    # Rate limit states (rolling window usage)
    anthropic_rate = get_rate_limit_status("anthropic")
    reddit_rate = get_rate_limit_status("reddit")
    
    # Recent job runs
    recent_jobs = query(
        """
        SELECT job_type, status, started_at, completed_at, items_processed, error_message
        FROM job_runs
        WHERE job_type = 'process_batch'
        ORDER BY started_at DESC
        LIMIT 5
        """
    )
    
    return {
        "queue_size": queue_size,
        "processing_count": processing_count,
        "monthly_spend_usd": round(monthly_spend, 4),
        "budget_limit_usd": MONTHLY_BUDGET_USD,
        "budget_remaining_usd": round(budget_remaining, 4),
        "budget_ok": monthly_spend < MONTHLY_BUDGET_USD,
        "backoff_states": {
            "anthropic": anthropic_backoff,
            "reddit": reddit_backoff,
        },
        "rate_limit_states": {
            "anthropic": anthropic_rate,
            "reddit": reddit_rate,
        },
        "recent_jobs": recent_jobs,
    }


# ============================================================
# Background Task Runner
# ============================================================

_worker_task: Optional[asyncio.Task] = None
_worker_running = False


async def _worker_loop(interval_seconds: int = 90):
    """Background loop that runs processing batches periodically."""
    global _worker_running
    print(f"[Worker] Background loop started (interval: {interval_seconds}s)")
    
    while _worker_running:
        try:
            await run_processing_batch(batch_size=20)
        except Exception as e:
            print(f"[Worker] Background batch error: {e}")
        
        # Wait for next interval
        await asyncio.sleep(interval_seconds)
    
    print("[Worker] Background loop stopped")


def start_background_worker(interval_seconds: int = 90):
    """Start the background worker task."""
    global _worker_task, _worker_running
    
    if _worker_running:
        print("[Worker] Already running")
        return
    
    _worker_running = True
    _worker_task = asyncio.create_task(_worker_loop(interval_seconds))
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
