"""
Exponential backoff utility for API rate limiting.
Uses the api_rate_limits table for persistent state across restarts.
"""

from datetime import datetime, timezone, timedelta
from db import query_one, execute

# Backoff durations by consecutive failure count
BACKOFF_MINUTES = {
    1: 1,    # 1st failure: 1 minute
    2: 5,    # 2nd failure: 5 minutes
    3: 30,   # 3+ failures: 30 minutes
}

# Rate limits per API (requests per minute)
RATE_LIMITS = {
    'reddit': {'requests_per_minute': 30, 'window_seconds': 60},
    'anthropic': {'requests_per_minute': 50, 'window_seconds': 60},
    'hackernews': {'requests_per_minute': 60, 'window_seconds': 60},  # HN Algolia is generous
}


def _get_backoff_minutes(failures: int) -> int:
    """Get backoff duration in minutes based on failure count."""
    if failures <= 0:
        return 0
    if failures == 1:
        return BACKOFF_MINUTES[1]
    if failures == 2:
        return BACKOFF_MINUTES[2]
    return BACKOFF_MINUTES[3]


def check_backoff(api_name: str) -> bool:
    """
    Check if it's OK to call this API.
    Returns True if OK to proceed, False if in backoff period.
    """
    row = query_one(
        "SELECT backoff_until FROM api_rate_limits WHERE api_name = %s",
        (api_name,)
    )
    
    if not row:
        # API not tracked yet, create entry
        execute(
            "INSERT INTO api_rate_limits (api_name) VALUES (%s) ON CONFLICT DO NOTHING",
            (api_name,)
        )
        return True
    
    backoff_until = row.get("backoff_until")
    if backoff_until is None:
        return True
    
    # Handle both datetime objects and strings
    if isinstance(backoff_until, str):
        backoff_until = datetime.fromisoformat(backoff_until.replace("Z", "+00:00"))
    
    now = datetime.now(timezone.utc)
    return now >= backoff_until


def record_success(api_name: str) -> None:
    """
    Record a successful API call. Resets consecutive failures and clears backoff.
    """
    now = datetime.now(timezone.utc)
    execute(
        """
        INSERT INTO api_rate_limits (api_name, consecutive_failures, backoff_until, last_success_at, last_error)
        VALUES (%s, 0, NULL, %s, NULL)
        ON CONFLICT (api_name) DO UPDATE SET
            consecutive_failures = 0,
            backoff_until = NULL,
            last_success_at = %s,
            last_error = NULL
        """,
        (api_name, now, now)
    )


def record_failure(api_name: str, error: str) -> None:
    """
    Record a failed API call. Increments consecutive failures and sets backoff.
    """
    now = datetime.now(timezone.utc)
    
    # Get current failure count
    row = query_one(
        "SELECT consecutive_failures FROM api_rate_limits WHERE api_name = %s",
        (api_name,)
    )
    
    if row:
        failures = (row.get("consecutive_failures") or 0) + 1
    else:
        failures = 1
    
    # Calculate backoff
    backoff_minutes = _get_backoff_minutes(failures)
    backoff_until = now + timedelta(minutes=backoff_minutes)
    
    execute(
        """
        INSERT INTO api_rate_limits (api_name, consecutive_failures, backoff_until, last_failure_at, last_error)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (api_name) DO UPDATE SET
            consecutive_failures = %s,
            backoff_until = %s,
            last_failure_at = %s,
            last_error = %s
        """,
        (api_name, failures, backoff_until, now, error[:500] if error else None,
         failures, backoff_until, now, error[:500] if error else None)
    )
    
    print(f"[Backoff] {api_name}: failure #{failures}, backing off until {backoff_until.isoformat()}")


def get_backoff_status(api_name: str) -> dict:
    """
    Get the current backoff status for an API.
    Returns dict with consecutive_failures, backoff_until, last_error, etc.
    """
    row = query_one(
        """
        SELECT api_name, consecutive_failures, backoff_until, 
               last_success_at, last_failure_at, last_error
        FROM api_rate_limits WHERE api_name = %s
        """,
        (api_name,)
    )
    
    if not row:
        return {
            "api_name": api_name,
            "consecutive_failures": 0,
            "backoff_until": None,
            "is_backing_off": False,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
        }
    
    backoff_until = row.get("backoff_until")
    is_backing_off = False
    if backoff_until:
        if isinstance(backoff_until, str):
            backoff_until = datetime.fromisoformat(backoff_until.replace("Z", "+00:00"))
        is_backing_off = datetime.now(timezone.utc) < backoff_until
    
    return {
        "api_name": row["api_name"],
        "consecutive_failures": row.get("consecutive_failures") or 0,
        "backoff_until": backoff_until.isoformat() if backoff_until else None,
        "is_backing_off": is_backing_off,
        "last_success_at": row.get("last_success_at"),
        "last_failure_at": row.get("last_failure_at"),
        "last_error": row.get("last_error"),
    }


# ============================================================
# Rolling Window Rate Limiting
# ============================================================
# Uses api_rate_limits table: requests_this_window, window_start
# This provides per-minute rate limiting on top of exponential backoff.

def check_rate_limit(api_name: str) -> bool:
    """
    Check if we're within the rate limit for this API.
    
    Uses api_rate_limits table fields:
    - requests_this_window: count of requests in current window
    - window_start: when the current window started
    
    Algorithm:
    1. If window_start > window_seconds ago, reset window
    2. If requests_this_window >= requests_per_minute, return False
    3. Otherwise return True
    
    Returns True if OK to proceed, False if rate limited.
    """
    limits = RATE_LIMITS.get(api_name)
    if not limits:
        # Unknown API - no rate limit
        return True
    
    max_requests = limits['requests_per_minute']
    window_seconds = limits['window_seconds']
    
    now = datetime.now(timezone.utc)
    
    row = query_one(
        """
        SELECT requests_this_window, window_start
        FROM api_rate_limits
        WHERE api_name = %s
        """,
        (api_name,)
    )
    
    if not row:
        # API not tracked yet - create entry with fresh window
        execute(
            """
            INSERT INTO api_rate_limits (api_name, requests_this_window, window_start)
            VALUES (%s, 0, %s)
            ON CONFLICT (api_name) DO NOTHING
            """,
            (api_name, now)
        )
        return True
    
    window_start = row.get("window_start")
    requests_count = row.get("requests_this_window") or 0
    
    # Handle window_start being None or missing
    if window_start is None:
        # Reset window
        execute(
            """
            UPDATE api_rate_limits 
            SET requests_this_window = 0, window_start = %s
            WHERE api_name = %s
            """,
            (now, api_name)
        )
        return True
    
    # Handle both datetime objects and strings
    if isinstance(window_start, str):
        window_start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
    
    # Check if window has expired
    window_age = (now - window_start).total_seconds()
    if window_age >= window_seconds:
        # Window expired - reset
        execute(
            """
            UPDATE api_rate_limits 
            SET requests_this_window = 0, window_start = %s
            WHERE api_name = %s
            """,
            (now, api_name)
        )
        return True
    
    # Check if we're at the limit
    if requests_count >= max_requests:
        remaining = window_seconds - window_age
        print(f"[RateLimit] {api_name}: rate limited ({requests_count}/{max_requests}), wait {remaining:.1f}s")
        return False
    
    return True


def record_request(api_name: str) -> None:
    """
    Record a request against the rate limit window.
    Call this AFTER a successful API call (or at the start of the call).
    Increments requests_this_window for this API.
    """
    limits = RATE_LIMITS.get(api_name)
    if not limits:
        return
    
    now = datetime.now(timezone.utc)
    
    # First try to increment existing row
    result = execute(
        """
        UPDATE api_rate_limits 
        SET requests_this_window = COALESCE(requests_this_window, 0) + 1
        WHERE api_name = %s
        RETURNING requests_this_window
        """,
        (api_name,)
    )
    
    if not result:
        # Row doesn't exist - create it with count=1
        execute(
            """
            INSERT INTO api_rate_limits (api_name, requests_this_window, window_start)
            VALUES (%s, 1, %s)
            ON CONFLICT (api_name) DO UPDATE SET
                requests_this_window = COALESCE(api_rate_limits.requests_this_window, 0) + 1
            """,
            (api_name, now)
        )


def check_rate_and_backoff(api_name: str) -> bool:
    """
    Combined check: both rate limit AND backoff must be OK.
    
    Returns True if:
    - Not in exponential backoff (from failures)
    - Not exceeding rate limit (requests/minute)
    """
    if not check_backoff(api_name):
        return False
    if not check_rate_limit(api_name):
        return False
    return True


def get_rate_limit_status(api_name: str) -> dict:
    """
    Get the current rate limit status for an API.
    Returns dict with requests_this_window, window_start, max_requests, etc.
    """
    limits = RATE_LIMITS.get(api_name, {'requests_per_minute': 60, 'window_seconds': 60})
    
    row = query_one(
        """
        SELECT requests_this_window, window_start
        FROM api_rate_limits
        WHERE api_name = %s
        """,
        (api_name,)
    )
    
    now = datetime.now(timezone.utc)
    
    if not row:
        return {
            "api_name": api_name,
            "requests_this_window": 0,
            "max_requests_per_minute": limits['requests_per_minute'],
            "window_seconds": limits['window_seconds'],
            "window_start": now.isoformat(),
            "window_remaining_sec": limits['window_seconds'],
            "is_rate_limited": False,
        }
    
    window_start = row.get("window_start")
    requests_count = row.get("requests_this_window") or 0
    
    if window_start and isinstance(window_start, str):
        window_start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
    
    if window_start:
        window_age = (now - window_start).total_seconds()
        window_remaining = max(0, limits['window_seconds'] - window_age)
        # Reset if window expired
        if window_age >= limits['window_seconds']:
            requests_count = 0
            window_remaining = limits['window_seconds']
    else:
        window_remaining = limits['window_seconds']
    
    is_limited = requests_count >= limits['requests_per_minute']
    
    return {
        "api_name": api_name,
        "requests_this_window": requests_count,
        "max_requests_per_minute": limits['requests_per_minute'],
        "window_seconds": limits['window_seconds'],
        "window_start": window_start.isoformat() if window_start else None,
        "window_remaining_sec": round(window_remaining, 1),
        "is_rate_limited": is_limited,
    }


# Async versions for use in async contexts (same logic, just async-compatible)
async def check_backoff_async(api_name: str) -> bool:
    """Async version of check_backoff (uses sync DB under the hood)."""
    return check_backoff(api_name)


async def record_success_async(api_name: str) -> None:
    """Async version of record_success."""
    record_success(api_name)


async def record_failure_async(api_name: str, error: str) -> None:
    """Async version of record_failure."""
    record_failure(api_name, error)


async def check_rate_limit_async(api_name: str) -> bool:
    """Async version of check_rate_limit."""
    return check_rate_limit(api_name)


async def record_request_async(api_name: str) -> None:
    """Async version of record_request."""
    record_request(api_name)


async def check_rate_and_backoff_async(api_name: str) -> bool:
    """Async version of check_rate_and_backoff."""
    return check_rate_and_backoff(api_name)
