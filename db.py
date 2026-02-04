"""
Direct PostgreSQL connection pool for Linksite.
Uses psycopg2 with a ThreadedConnectionPool for connection reuse.
Connections use autocommit=True to avoid implicit transaction overhead.
"""

import os
import threading
from contextlib import contextmanager
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

# Connection pool singleton
_pool = None
_pool_lock = threading.Lock()

DEFAULT_DATABASE_URL = 'postgresql://postgres:0JvN0xPnOFcxPbmm@db.rsjcdwmgbxthsuyspndt.supabase.co:5432/postgres'


def get_pool(min_conn=2, max_conn=10):
    """Get or create the connection pool singleton."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        database_url = os.getenv('DATABASE_URL', DEFAULT_DATABASE_URL)
        _pool = pg_pool.ThreadedConnectionPool(
            min_conn, max_conn, database_url
        )
        # Set autocommit on initial pooled connections
        # (avoids implicit BEGIN/COMMIT per query â€” saves 2 round trips)
        for _ in range(min_conn):
            conn = _pool.getconn()
            conn.autocommit = True
            _pool.putconn(conn)
        return _pool


def close_pool():
    """Close all connections in the pool."""
    global _pool
    with _pool_lock:
        if _pool:
            _pool.closeall()
            _pool = None


@contextmanager
def get_conn():
    """Context manager: get a connection from the pool, auto-return.
    
    Connection has autocommit=True for SELECTs. 
    For write operations needing transactions, use get_conn_transaction().
    """
    p = get_pool()
    conn = p.getconn()
    conn.autocommit = True
    try:
        yield conn
    finally:
        p.putconn(conn)


@contextmanager
def get_conn_transaction():
    """Context manager: get a connection with explicit transaction control.
    
    Auto-commits on success, rolls back on exception.
    """
    p = get_pool()
    conn = p.getconn()
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True
        p.putconn(conn)


def query(sql, params=None):
    """Execute a query and return list of dicts."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                return cur.fetchall()
            return []


def execute(sql, params=None):
    """Execute a statement (INSERT/UPDATE/DELETE) and return results."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                return cur.fetchall()
            return []


def query_one(sql, params=None):
    """Execute a query and return a single row (or None)."""
    rows = query(sql, params)
    return rows[0] if rows else None
