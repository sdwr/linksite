#!/usr/bin/env python3
"""Run schema_ai_v2.sql migration using the existing DB connection."""

import os
import sys

# Add the app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn

# Read SQL file
sql_file = os.path.join(os.path.dirname(__file__), "schema_ai_v2.sql")
with open(sql_file, "r") as f:
    sql = f.read()

# Connect and execute
print("Running migration using app DB connection...")

with get_conn() as conn:
    cur = conn.cursor()
    try:
        cur.execute(sql)
        print("Migration completed successfully!")
    except Exception as e:
        print(f"Migration error: {e}")
        sys.exit(1)
    finally:
        cur.close()
