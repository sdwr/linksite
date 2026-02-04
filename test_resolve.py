#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from scratchpad_api import resolve_reddit_url

url = "https://reddit.com/r/technology/comments/1qv9kcb/"
print(f"Resolving: {url}")
result = resolve_reddit_url(url)
print(f"Result: {result}")
