"""
Compare Opus vs Sonnet summaries for 10 links.
Run from sprite: python compare_summaries.py
"""

import os
import asyncio
import httpx
from datetime import datetime

# Direct DB connection
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres.rsjcdwmgbxthsuyspndt:0JvN0xPnOFcxPbmm@aws-0-us-east-1.pooler.supabase.com:5432/postgres')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# Sonnet model
SONNET_MODEL = "claude-sonnet-4-20250514"

def summary_prompt(title: str, url: str, content: str) -> str:
    """TL;DR summary prompt - same as in prompts.py"""
    content_preview = content[:4000] if content else "(no content extracted)"
    return f"""Write a TL;DR summary of this link in 2-4 sentences. Be specific - include key facts, numbers, or conclusions.
Focus on what makes this interesting or noteworthy.

Title: {title}
URL: {url}
Content:
{content_preview}

Return ONLY the summary text (2-4 sentences), nothing else."""


async def call_sonnet(prompt: str, http: httpx.AsyncClient) -> dict:
    """Call Claude Sonnet API."""
    payload = {
        "model": SONNET_MODEL,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    
    resp = await http.post(ANTHROPIC_API_URL, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block["text"]
    
    usage = data.get("usage", {})
    return {
        "text": text.strip(),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


async def main():
    # Connect to DB
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Fetch 10 links with existing summaries
    cur.execute("""
        SELECT id, url, title, description, content, summary
        FROM links
        WHERE summary IS NOT NULL AND summary != ''
        ORDER BY created_at DESC
        LIMIT 10
    """)
    links = cur.fetchall()
    
    if not links:
        print("No links with summaries found!")
        return
    
    print(f"Found {len(links)} links with existing (Haiku) summaries\n")
    print("=" * 80)
    
    async with httpx.AsyncClient(timeout=60.0) as http:
        total_input = 0
        total_output = 0
        
        for i, link in enumerate(links, 1):
            print(f"\n[{i}] {link['title'][:60]}...")
            print(f"    URL: {link['url'][:70]}...")
            
            # Existing summary (generated with Haiku based on the code)
            existing = link['summary'] or "(none)"
            print(f"\n    HAIKU SUMMARY:")
            print(f"    {existing}")
            
            # Generate new summary with Sonnet
            content = link.get('content') or link.get('description') or ''
            prompt = summary_prompt(link['title'] or '', link['url'] or '', content)
            
            try:
                result = await call_sonnet(prompt, http)
                sonnet_summary = result['text']
                total_input += result['input_tokens']
                total_output += result['output_tokens']
                
                print(f"\n    SONNET SUMMARY:")
                print(f"    {sonnet_summary}")
            except Exception as e:
                print(f"\n    SONNET ERROR: {e}")
            
            print("\n" + "-" * 80)
        
        # Cost calculation for Sonnet
        # Sonnet: $3/1M input, $15/1M output
        cost = (total_input * 3.0 + total_output * 15.0) / 1_000_000
        print(f"\nSONNET TOTALS: {total_input} input + {total_output} output tokens")
        print(f"ESTIMATED COST: ${cost:.4f}")
    
    cur.close()
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
