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
