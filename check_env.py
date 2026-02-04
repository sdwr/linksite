#!/usr/bin/env python3
"""Check environment variables."""

import os
print(f"Before dotenv: DATABASE_URL = {os.getenv('DATABASE_URL', 'NOT SET')}")

from dotenv import load_dotenv
load_dotenv()

print(f"After dotenv: DATABASE_URL = {os.getenv('DATABASE_URL', 'NOT SET')}")

# Also check what the db module uses
from db import DEFAULT_DATABASE_URL
print(f"DEFAULT_DATABASE_URL = {DEFAULT_DATABASE_URL[:60]}...")
