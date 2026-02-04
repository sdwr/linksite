#!/usr/bin/env python3
"""Check if schema migrations have been applied."""

from dotenv import load_dotenv
load_dotenv()

from db_compat import CompatClient

db = CompatClient()

# Check job_runs table
try:
    result = db.table("job_runs").select("id").limit(1).execute()
    print(f"job_runs table exists: {len(result.data)} rows")
except Exception as e:
    print(f"job_runs table ERROR: {e}")

# Check processing_status column on links
try:
    result = db.table("links").select("processing_status").limit(1).execute()
    print(f"processing_status column exists: {result.data}")
except Exception as e:
    print(f"processing_status column ERROR: {e}")
