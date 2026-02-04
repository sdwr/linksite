#!/usr/bin/env python3
"""Test direct database connection."""

import psycopg2

url = "postgresql://postgres.rsjcdwmgbxthsuyspndt:0JvN0xPnOFcxPbmm@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require"

print(f"Connecting to: {url[:60]}...")

try:
    conn = psycopg2.connect(url)
    print("Connection successful!")
    
    # Test a simple query
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM links")
    count = cur.fetchone()[0]
    print(f"Links count: {count}")
    
    # Check if job_runs exists
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'job_runs')")
    exists = cur.fetchone()[0]
    print(f"job_runs table exists: {exists}")
    
    # Check if processing_status column exists
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_name = 'links' AND column_name = 'processing_status'
        )
    """)
    exists = cur.fetchone()[0]
    print(f"processing_status column exists: {exists}")
    
    conn.close()
except Exception as e:
    print(f"Connection failed: {e}")
