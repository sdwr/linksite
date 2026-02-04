#!/usr/bin/env python3
"""Test database connection."""

import os
from dotenv import load_dotenv
load_dotenv()

db_url = os.getenv("DATABASE_URL", "NOT SET")
print(f"DATABASE_URL = {db_url[:50]}...")

import psycopg2
try:
    conn = psycopg2.connect(db_url)
    print("Connection successful!")
    conn.close()
except Exception as e:
    print(f"Connection failed: {e}")
