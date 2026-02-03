"""
Supabase-py compatible wrapper over direct psycopg2 connections.

Provides a drop-in replacement for the supabase-py Client's table() API:
    client = CompatClient()
    result = client.table('links').select('*').eq('id', 1).execute()
    result.data   # [{'id': 1, ...}]
    result.count  # int (when count='exact')

Supports: select, insert, update, delete, upsert
Filters: eq, neq, in_, or_, ilike, gte, gt, lte, lt, like, is_
Modifiers: order, limit, range
"""

import re
import json
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from uuid import UUID
from psycopg2.extras import RealDictCursor, Json
from db import get_conn


def _serialize_value(val):
    """Convert psycopg2 native types to JSON-serializable types matching supabase-py output."""
    if val is None:
        return None
    if isinstance(val, datetime):
        # Supabase returns ISO 8601 with timezone, e.g. "2024-01-15T10:30:00+00:00"
        s = val.isoformat()
        # Ensure timezone info is present
        if val.tzinfo is None:
            s += "+00:00"
        return s
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, time):
        return val.isoformat()
    if isinstance(val, timedelta):
        return val.total_seconds()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, memoryview):
        return bytes(val).hex()
    return val


def _serialize_row(row: dict) -> dict:
    """Convert all values in a row to match supabase-py's JSON output format."""
    return {k: _serialize_value(v) for k, v in row.items()}


class CompatResponse:
    """Mimics the supabase-py APIResponse."""
    __slots__ = ('data', 'count')

    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class TableQuery:
    """Fluent query builder that mimics supabase-py's table().select().eq().execute() chain."""

    def __init__(self, table_name):
        self._table = table_name
        self._operation = None  # 'select', 'insert', 'update', 'delete', 'upsert'
        self._columns = '*'
        self._count_mode = None  # None or 'exact'
        self._filters = []      # [(column, op, value), ...]
        self._or_filters = []   # raw PostgREST-style OR strings
        self._order_by = []     # [(column, desc_bool), ...]
        self._limit_val = None
        self._offset_val = None
        self._range_from = None
        self._range_to = None
        self._insert_data = None
        self._update_data = None
        self._upsert_data = None
        self._on_conflict = None

    # --- Operations ---

    def select(self, columns='*', count=None):
        self._operation = 'select'
        self._columns = columns
        self._count_mode = count
        return self

    def insert(self, data):
        self._operation = 'insert'
        self._insert_data = data
        return self

    def update(self, data):
        self._operation = 'update'
        self._update_data = data
        return self

    def delete(self):
        self._operation = 'delete'
        return self

    def upsert(self, data, on_conflict=None):
        self._operation = 'upsert'
        self._upsert_data = data
        self._on_conflict = on_conflict
        return self

    # --- Filters ---

    def eq(self, column, value):
        self._filters.append((column, '=', value))
        return self

    def neq(self, column, value):
        self._filters.append((column, '!=', value))
        return self

    def gt(self, column, value):
        self._filters.append((column, '>', value))
        return self

    def gte(self, column, value):
        self._filters.append((column, '>=', value))
        return self

    def lt(self, column, value):
        self._filters.append((column, '<', value))
        return self

    def lte(self, column, value):
        self._filters.append((column, '<=', value))
        return self

    def like(self, column, pattern):
        self._filters.append((column, 'LIKE', pattern))
        return self

    def ilike(self, column, pattern):
        self._filters.append((column, 'ILIKE', pattern))
        return self

    def is_(self, column, value):
        self._filters.append((column, 'IS', value))
        return self

    def in_(self, column, values):
        if not values:
            # Empty IN â€” force no results
            self._filters.append(('1', '=', '0'))
        else:
            self._filters.append((column, 'IN', tuple(values)))
        return self

    def or_(self, filter_str):
        """Parse PostgREST-style OR filter string.
        
        Example: 'title.ilike.%q%,url.ilike.%q%,description.ilike.%q%'
        """
        self._or_filters.append(filter_str)
        return self

    # --- Modifiers ---

    def order(self, column, desc=False):
        self._order_by.append((column, desc))
        return self

    def limit(self, n):
        self._limit_val = n
        return self

    def range(self, start, end):
        self._range_from = start
        self._range_to = end
        return self

    # --- Execution ---

    def execute(self):
        if self._operation == 'select':
            return self._exec_select()
        elif self._operation == 'insert':
            return self._exec_insert()
        elif self._operation == 'update':
            return self._exec_update()
        elif self._operation == 'delete':
            return self._exec_delete()
        elif self._operation == 'upsert':
            return self._exec_upsert()
        else:
            raise ValueError(f"No operation set. Call select/insert/update/delete first.")

    def _build_where(self, params):
        """Build WHERE clause from filters. Returns (clause_str, params_list)."""
        conditions = []
        
        for col, op, val in self._filters:
            placeholder = f'%s'
            if op == 'IN':
                conditions.append(f'"{col}" IN %s')
                params.append(val)  # tuple
            elif op == 'IS':
                if val is None:
                    conditions.append(f'"{col}" IS NULL')
                elif val == 'null':
                    conditions.append(f'"{col}" IS NULL')
                else:
                    conditions.append(f'"{col}" IS {val}')
            elif col == '1' and op == '=' and val == '0':
                conditions.append('FALSE')
            else:
                conditions.append(f'"{col}" {op} {placeholder}')
                params.append(val)

        # Handle OR filters (PostgREST format)
        for or_str in self._or_filters:
            or_parts = self._parse_or_filter(or_str, params)
            if or_parts:
                conditions.append(f'({" OR ".join(or_parts)})')

        if conditions:
            return ' WHERE ' + ' AND '.join(conditions)
        return ''

    def _parse_or_filter(self, filter_str, params):
        """Parse PostgREST OR filter string like 'title.ilike.%q%,url.ilike.%q%'"""
        parts = []
        # Split on commas, but handle dots in values
        # Format: column.operator.value
        segments = re.split(r',(?=[a-zA-Z_])', filter_str)
        for seg in segments:
            match = re.match(r'^(\w+)\.(eq|neq|gt|gte|lt|lte|like|ilike|is)\.(.+)$', seg.strip())
            if match:
                col, op, val = match.groups()
                sql_op_map = {
                    'eq': '=', 'neq': '!=', 'gt': '>', 'gte': '>=',
                    'lt': '<', 'lte': '<=', 'like': 'LIKE', 'ilike': 'ILIKE',
                    'is': 'IS',
                }
                sql_op = sql_op_map.get(op, '=')
                if sql_op == 'IS':
                    if val.lower() == 'null':
                        parts.append(f'"{col}" IS NULL')
                    else:
                        parts.append(f'"{col}" IS {val}')
                else:
                    parts.append(f'"{col}" {sql_op} %s')
                    params.append(val)
        return parts

    def _build_order(self):
        if not self._order_by:
            return ''
        parts = []
        for col, desc in self._order_by:
            parts.append(f'"{col}" {"DESC" if desc else "ASC"}')
        return ' ORDER BY ' + ', '.join(parts)

    def _build_limit(self):
        parts = ''
        if self._limit_val is not None:
            parts += f' LIMIT {int(self._limit_val)}'
        if self._offset_val is not None:
            parts += f' OFFSET {int(self._offset_val)}'
        if self._range_from is not None:
            limit = self._range_to - self._range_from + 1
            parts = f' LIMIT {limit} OFFSET {self._range_from}'
        return parts

    def _select_columns(self):
        """Convert supabase-style column string to SQL."""
        cols = self._columns.strip()
        if cols == '*':
            return '*'
        # Split by comma and quote each column name
        parts = []
        for c in cols.split(','):
            c = c.strip()
            if c:
                parts.append(f'"{c}"')
        return ', '.join(parts) if parts else '*'

    def _exec_select(self):
        params = []
        cols = self._select_columns()
        sql = f'SELECT {cols} FROM "{self._table}"'
        sql += self._build_where(params)
        sql += self._build_order()
        sql += self._build_limit()

        count = None
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params if params else None)
                rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
                
                # Convert special types
                for row in rows:
                    for key, val in row.items():
                        # Convert psycopg2's json columns properly
                        pass  # RealDictCursor handles most types

                if self._count_mode == 'exact':
                    # Run a separate COUNT query
                    count_params = []
                    count_sql = f'SELECT COUNT(*) as cnt FROM "{self._table}"'
                    count_sql += self._build_where(count_params)
                    cur.execute(count_sql, count_params if count_params else None)
                    count = cur.fetchone()['cnt']

        return CompatResponse(data=rows, count=count)

    def _exec_insert(self):
        data = self._insert_data
        if not data:
            return CompatResponse()

        if isinstance(data, list):
            # Batch insert
            if not data:
                return CompatResponse()
            keys = list(data[0].keys())
        else:
            keys = list(data.keys())
            data = [data]

        cols = ', '.join(f'"{k}"' for k in keys)
        placeholders = ', '.join(['%s'] * len(keys))
        sql = f'INSERT INTO "{self._table}" ({cols}) VALUES ({placeholders}) RETURNING *'

        all_rows = []
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for row_data in data:
                    values = [_prep_value(row_data.get(k)) for k in keys]
                    cur.execute(sql, values)
                    result = cur.fetchall()
                    all_rows.extend(_serialize_row(dict(r)) for r in result)

        return CompatResponse(data=all_rows)

    def _exec_update(self):
        data = self._update_data
        if not data:
            return CompatResponse()

        set_parts = []
        params = []
        for k, v in data.items():
            set_parts.append(f'"{k}" = %s')
            params.append(_prep_value(v))

        sql = f'UPDATE "{self._table}" SET {", ".join(set_parts)}'
        sql += self._build_where(params)
        sql += ' RETURNING *'

        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [_serialize_row(dict(r)) for r in cur.fetchall()]

        return CompatResponse(data=rows)

    def _exec_delete(self):
        params = []
        sql = f'DELETE FROM "{self._table}"'
        sql += self._build_where(params)
        sql += ' RETURNING *'

        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [_serialize_row(dict(r)) for r in cur.fetchall()]

        return CompatResponse(data=rows)

    def _exec_upsert(self):
        data = self._upsert_data
        if not data:
            return CompatResponse()

        if isinstance(data, list):
            if not data:
                return CompatResponse()
            keys = list(data[0].keys())
        else:
            keys = list(data.keys())
            data = [data]

        cols = ', '.join(f'"{k}"' for k in keys)
        placeholders = ', '.join(['%s'] * len(keys))

        # Build ON CONFLICT clause
        conflict_cols = self._on_conflict or 'id'
        conflict_parts = ', '.join(f'"{c.strip()}"' for c in conflict_cols.split(','))

        # Build SET clause for upsert (update all non-conflict columns)
        update_parts = []
        for k in keys:
            if k not in [c.strip() for c in conflict_cols.split(',')]:
                update_parts.append(f'"{k}" = EXCLUDED."{k}"')

        if update_parts:
            conflict_action = f'UPDATE SET {", ".join(update_parts)}'
        else:
            conflict_action = 'NOTHING'

        sql = (f'INSERT INTO "{self._table}" ({cols}) VALUES ({placeholders}) '
               f'ON CONFLICT ({conflict_parts}) DO {conflict_action} '
               f'RETURNING *')

        all_rows = []
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for row_data in data:
                    values = [_prep_value(row_data.get(k)) for k in keys]
                    cur.execute(sql, values)
                    result = cur.fetchall()
                    all_rows.extend(_serialize_row(dict(r)) for r in result)

        return CompatResponse(data=all_rows)


def _prep_value(val):
    """Prepare a Python value for psycopg2 parameter binding."""
    if isinstance(val, dict):
        return Json(val)
    if isinstance(val, list):
        # Check if it's a list of floats (vector) or regular list
        if val and isinstance(val[0], (int, float)):
            # Could be a pgvector embedding â€” pass as string representation
            return str(val)
        return Json(val)
    return val


class CompatClient:
    """Drop-in replacement for supabase.Client â€” just the table() API."""

    def table(self, name):
        return TableQuery(name)


# Module-level singleton
_client = None

def get_client():
    global _client
    if _client is None:
        _client = CompatClient()
    return _client
