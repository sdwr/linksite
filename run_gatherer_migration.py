#!/usr/bin/env python3
"""Run the gatherer schema migration."""

from dotenv import load_dotenv
load_dotenv()

import psycopg2
from db import get_conn

# Read the migration SQL
with open('schema_gatherer.sql', 'r') as f:
    sql = f.read()

# Execute it
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
        print('Migration executed successfully!')
