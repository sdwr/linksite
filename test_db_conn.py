#!/usr/bin/env python3
"""Quick test of DB connection with new password."""
import os
os.chdir('/home/sprite/linksite')

import psycopg2

# Test pooler connection
pooler_url = "postgresql://postgres.rsjcdwmgbxthsuyspndt:nPApeCGY5sdGFzNu@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require"

try:
    conn = psycopg2.connect(pooler_url)
    print("POOLER: OK")
    conn.close()
except Exception as e:
    print(f"POOLER: FAILED - {e}")

# Test direct connection
direct_url = "postgresql://postgres:nPApeCGY5sdGFzNu@db.rsjcdwmgbxthsuyspndt.supabase.co:5432/postgres"

try:
    conn = psycopg2.connect(direct_url)
    print("DIRECT: OK")
    conn.close()
except Exception as e:
    print(f"DIRECT: FAILED - {e}")
