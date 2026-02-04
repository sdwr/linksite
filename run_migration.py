#!/usr/bin/env python3
"""Run schema_ai_v2.sql migration using the existing DB connection."""

import os
import sys
import psycopg2

# Get connection string from environment
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# Read SQL file
sql_file = os.path.join(os.path.dirname(__file__), "schema_ai_v2.sql")
with open(sql_file, "r") as f:
    sql = f.read()

# Connect and execute
print(f"Connecting to database...")
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# Execute the SQL
print("Running migration...")
try:
    cur.execute(sql)
    print("Migration completed successfully!")
except Exception as e:
    print(f"Migration error: {e}")
    sys.exit(1)
finally:
    cur.close()
    conn.close()
