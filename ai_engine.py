"""
AI Content Engine — Core Logic

Integrates with the Linksite FastAPI app to discover and enrich links
using Claude AI models. All operations are tracked in ai_runs and
ai_generated_content tables.

Features:
- Link discovery from web search and Hacker News
- Summary generation for links
- AI comments from multiple personas
- Token usage tracking
- Prioritized enrichment queue

Usage:
    from ai_engine import AIEngine
    engine = AIEngine(supabase_client)
    
    # Discover new links
    result = await engine.discover_links(topic="AI safety", count=5)
    
    # Generate summary for a link
    result = await engine.generate_summary(link_id=123)
    
    # Enrich a single link
    result = await engine.enrich_link(link_id=123)
    
    # Batch enrich (with prioritization)
    result = await engine.enrich_batch(limit=10)
"""

import os
import json
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import uuid4

from scratchpad_api import normalize_url

from prompts import (
    discovery_filter_prompt,
    discovery_hn_prompt,
    description_prompt,
    tag_suggestions_prompt,
    summary_prompt,
    PERSONAS,
    PROMPT_FUNCTIONS,
    get_persona,
    get_active_personas,
    build_comment_prompt,
)

# ============================================================
# Model Configuration & Pricing
# ============================================================

MODELS = {
    "haiku": "claude-3-5-haiku-20241022",
    "sonnet": "claude-sonnet-4-20250514",
}

# Pricing per 1M tokens (as of 2024)
MODEL_PRICING = {
    "claude-3-5-haiku-20241022": {"input": 0.25, "output": 1.25},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    # Fallback for unknown models
    "default": {"input": 1.00, "output": 5.00},
}

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# ============================================================
# AI Engine
# ============================================================

class AIEngine:
    """Core AI Content Engine for Linksite."""

    def __init__(self, supabase_client, anthropic_api_key: str = None,
                 brave_api_key: str = None, vectorize_fn=None):
        self.supabase = supabase_client
        self.api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.brave_key = brave_api_key or os.getenv("BRAVE_API_KEY", "")
        self.vectorize = vectorize_fn  # Optional: function to generate embeddings
        self._http = None
        self._personas_cache = None
        self._personas_cache_time = 0

    @property
    def http(self):
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=60.0)
        return self._http

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None

    # --------------------------------------------------------
    # Persona Management
    # --------------------------------------------------------

    def _get_personas(self, force_refresh: bool = False) -> dict:
        """Get personas, using DB config if available, else defaults."""
        now = datetime.now(timezone.utc).timestamp()
        
        # Cache for 5 minutes
        if not force_refresh and self._personas_cache and (now - self._personas_cache_time) < 300:
            return self._personas_cache
        
        personas = dict(PERSONAS)  # Start with defaults
        
        try:
            resp = self.supabase.table("ai_personas").select("*").eq("is_active", True).execute()
            if resp.data:
                for row in resp.data:
                    pid = row.get("id")
                    if pid:
                        # Merge DB config with defaults
                        base = personas.get(pid, {})
                        prompt_fn = PROMPT_FUNCTIONS.get(pid)
                        
                        personas[pid] = {
                            "id": pid,
                            "author": f"ai-{pid}",
                            "prompt_fn": prompt_fn,
                            "model": row.get("model") or base.get("model", "haiku"),
                            "description": row.get("description") or base.get("description", ""),
                            "priority": row.get("priority") or base.get("priority", 50),
                            "system_prompt": row.get("system_prompt"),
                            "user_prompt_template": row.get("user_prompt_template"),
                        }
        except Exception as e:
            print(f"[AIEngine] Failed to load personas from DB: {e}")
        
        self._personas_cache = personas
        self._personas_cache_time = now
        return personas

    # --------------------------------------------------------
    # Claude API
    # --------------------------------------------------------

    async def _call_claude(self, prompt: str, model_key: str = "haiku",
                           max_tokens: int = 1024, system: str = None,
                           operation_type: str = None, link_id: int = None,
                           run_id: str = None) -> dict:
        """
        Call Claude API and return response + token usage.
        
        Tracks token usage in ai_token_usage table.
        """
        model = MODELS.get(model_key, MODELS["haiku"])
        
        messages = [{"role": "user", "content": prompt}]
        
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        resp = await self.http.post(ANTHROPIC_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        # Extract detailed usage
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = input_tokens + output_tokens
        
        # Calculate estimated cost
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        estimated_cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        # Track token usage
        self._record_token_usage(
            run_id=run_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost,
            operation_type=operation_type,
            link_id=link_id,
        )

        return {
            "text": text,
            "tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": estimated_cost,
            "model": model_key,
        }

    def _parse_json_response(self, text: str) -> any:
        """Extract JSON from a Claude response (handles markdown code blocks)."""
        text = text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (``` markers)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array/object in the text
            for start_char, end_char in [("[", "]"), ("{", "}")]:
                start = text.find(start_char)
                end = text.rfind(end_char)
                if start != -1 and end != -1 and end > start:
                    try:
                        return json.loads(text[start:end + 1])
                    except json.JSONDecodeError:
                        continue
            return None

    # --------------------------------------------------------
    # Token Usage Tracking
    # --------------------------------------------------------

    def _record_token_usage(self, run_id: str, model: str, input_tokens: int,
                            output_tokens: int, total_tokens: int,
                            estimated_cost: float, operation_type: str = None,
                            link_id: int = None):
        """Record detailed token usage to the database."""
        try:
            self.supabase.table("ai_token_usage").insert({
                "run_id": run_id,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": estimated_cost,
                "operation_type": operation_type,
                "link_id": link_id,
            }).execute()
        except Exception as e:
            # Don't fail the main operation if tracking fails
            print(f"[AIEngine] Token usage tracking failed: {e}")

    async def get_token_usage_stats(self, days: int = 30) -> dict:
        """Get token usage statistics for the specified period."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        try:
            resp = self.supabase.table("ai_token_usage").select(
                "model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, operation_type"
            ).gte("created_at", cutoff).execute()
            
            records = resp.data or []
            
            total_input = sum(r.get("input_tokens", 0) for r in records)
            total_output = sum(r.get("output_tokens", 0) for r in records)
            total_cost = sum(float(r.get("estimated_cost_usd", 0)) for r in records)
            
            by_model = {}
            by_operation = {}
            
            for r in records:
                model = r.get("model", "unknown")
                if model not in by_model:
                    by_model[model] = {"tokens": 0, "cost": 0, "calls": 0}
                by_model[model]["tokens"] += r.get("total_tokens", 0)
                by_model[model]["cost"] += float(r.get("estimated_cost_usd", 0))
                by_model[model]["calls"] += 1
                
                op = r.get("operation_type", "unknown")
                if op not in by_operation:
                    by_operation[op] = {"tokens": 0, "cost": 0, "calls": 0}
                by_operation[op]["tokens"] += r.get("total_tokens", 0)
                by_operation[op]["cost"] += float(r.get("estimated_cost_usd", 0))
                by_operation[op]["calls"] += 1
            
            return {
                "period_days": days,
                "total_calls": len(records),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_tokens": total_input + total_output,
                "total_cost_usd": round(total_cost, 4),
                "by_model": by_model,
                "by_operation": by_operation,
            }
        except Exception as e:
            return {"error": str(e)}

    # --------------------------------------------------------
    # Run Tracking
    # --------------------------------------------------------

    def _create_run(self, run_type: str, params: dict) -> str:
        """Create a new ai_runs record. Returns run_id."""
        run_id = str(uuid4())
        self.supabase.table("ai_runs").insert({
            "id": run_id,
            "type": run_type,
            "params": params,
            "status": "running",
        }).execute()
        return run_id

    def _complete_run(self, run_id: str, results_count: int, tokens_used: int,
                      model: str, error: str = None):
        """Mark a run as completed or failed."""
        update = {
            "results_count": results_count,
            "tokens_used": tokens_used,
            "model": model,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            update["status"] = "failed"
            update["error"] = error[:1000]
        else:
            update["status"] = "completed"

        self.supabase.table("ai_runs").update(update).eq("id", run_id).execute()

    def _record_content(self, run_id: str, link_id: int, content_type: str,
                        content: str, author: str = None, model_used: str = None,
                        tokens_used: int = 0, persona_id: str = None):
        """Record a piece of generated content."""
        self.supabase.table("ai_generated_content").insert({
            "run_id": run_id,
            "link_id": link_id,
            "content_type": content_type,
            "content": content,
            "author": author,
            "model_used": model_used,
            "tokens_used": tokens_used,
            "persona_id": persona_id,
        }).execute()

    # --------------------------------------------------------
    # Web Search (Brave API)
    # --------------------------------------------------------

    async def _brave_search(self, query: str, count: int = 10) -> list[dict]:
        """Search the web using Brave Search API."""
        if not self.brave_key:
            return []

        params = {
            "q": query,
            "count": min(count, 20),
            "freshness": "pw",  # past week
        }
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.brave_key,
        }

        resp = await self.http.get(
            "https://api.search.brave.com/res/v1/web/search",
            params=params, headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("web", {}).get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
            })
        return results

    async def _fetch_hn_top(self, count: int = 30) -> list[dict]:
        """Fetch top stories from Hacker News API."""
        resp = await self.http.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        )
        story_ids = resp.json()[:count]

        items = []
        # Fetch stories in parallel (batches of 10)
        for batch_start in range(0, len(story_ids), 10):
            batch = story_ids[batch_start:batch_start + 10]
            tasks = [
                self.http.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                for sid in batch
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for r in responses:
                if isinstance(r, Exception):
                    continue
                data = r.json()
                if data and data.get("url"):
                    items.append({
                        "title": data.get("title", ""),
                        "url": data.get("url", ""),
                        "score": data.get("score", 0),
                        "descendants": data.get("descendants", 0),
                        "hn_id": data.get("id"),
                    })
        return items

    # --------------------------------------------------------
    # Prioritization
    # --------------------------------------------------------

    def _calculate_priority_score(self, link: dict) -> float:
        """
        Calculate priority score for enrichment.
        
        Higher score = should be processed first.
        
        Factors:
        - Engagement (direct_score, times_shown)
        - Recency (created_at)
        - Existing enrichment (lower priority if already has content)
        """
        score = 0.0
        
        # Engagement boost (up to 50 points)
        direct_score = link.get("direct_score") or 0
        times_shown = link.get("times_shown") or 0
        view_count = link.get("view_count") or 0
        
        score += min(direct_score * 5, 25)  # Up to 25 from votes
        score += min(times_shown * 2, 15)   # Up to 15 from being featured
        score += min(view_count * 0.5, 10)  # Up to 10 from views
        
        # Recency boost (up to 40 points)
        created_at = link.get("created_at")
        if created_at:
            try:
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - created_at).days
                
                if age_days <= 1:
                    score += 40  # Very recent
                elif age_days <= 3:
                    score += 30
                elif age_days <= 7:
                    score += 20
                elif age_days <= 30:
                    score += 10
                # Older than 30 days gets no recency boost
            except Exception:
                pass
        
        # Penalty for already enriched content
        if link.get("summary"):
            score -= 10
        if link.get("description") and len(link.get("description", "")) > 50:
            score -= 5
        
        return score

    def _get_prioritized_links(self, limit: int = 20, needs_summary: bool = True,
                                needs_comments: bool = True) -> list[dict]:
        """
        Get links prioritized for enrichment.
        
        Returns links sorted by priority score (highest first).
        """
        # Fetch recent links with engagement data
        query = self.supabase.table("links").select(
            "id, url, title, description, content, summary, source, "
            "direct_score, times_shown, view_count, created_at"
        ).neq("source", "auto-parent").order(
            "created_at", desc=True
        ).limit(limit * 5)  # Fetch extra for filtering/sorting
        
        resp = query.execute()
        links = resp.data or []
        
        # Filter based on what's needed
        candidates = []
        for link in links:
            needs_work = False
            
            if needs_summary and not link.get("summary"):
                needs_work = True
            
            if needs_comments:
                # Check for existing AI comments
                notes = self.supabase.table("notes").select("id").eq(
                    "link_id", link["id"]
                ).ilike("author", "ai-%").limit(1).execute()
                if not notes.data:
                    needs_work = True
            
            if needs_work:
                link["_priority"] = self._calculate_priority_score(link)
                candidates.append(link)
        
        # Sort by priority (highest first)
        candidates.sort(key=lambda x: x.get("_priority", 0), reverse=True)
        
        return candidates[:limit]

    # --------------------------------------------------------
    # Summary Generation
    # --------------------------------------------------------

    async def generate_summary(self, link_id: int) -> dict:
        """
        Generate a summary for a single link.
        
        This is separate from comments — summaries are stored on the link itself.
        
        Returns:
            {"link_id": int, "summary": str, "tokens": int, "error": str?}
        """
        params = {"link_id": link_id, "type": "summary"}
        run_id = self._create_run("enrich", params)
        total_tokens = 0
        model_used = "haiku"

        try:
            # Fetch the link
            link_resp = self.supabase.table("links").select(
                "id, url, title, description, content, summary"
            ).eq("id", link_id).execute()

            if not link_resp.data:
                raise ValueError(f"Link {link_id} not found")

            link = link_resp.data[0]
            
            # Skip if already has a summary
            if link.get("summary") and len(link.get("summary", "")) > 20:
                self._complete_run(run_id, 0, 0, model_used)
                return {
                    "link_id": link_id,
                    "summary": link["summary"],
                    "skipped": True,
                    "reason": "Already has summary",
                }

            title = link.get("title") or ""
            url = link.get("url") or ""
            content = link.get("content") or link.get("description") or ""

            if not title and not content:
                raise ValueError(f"Link {link_id} has no title or content to summarize")

            # Generate summary
            prompt = summary_prompt(title, url, content)
            result = await self._call_claude(
                prompt, "haiku", max_tokens=300,
                operation_type="summary", link_id=link_id, run_id=run_id
            )
            total_tokens = result["tokens"]

            summary_text = result["text"].strip()
            if summary_text and len(summary_text) > 20:
                # Store summary on the link
                self.supabase.table("links").update(
                    {"summary": summary_text}
                ).eq("id", link_id).execute()

                # Record in ai_generated_content
                self._record_content(
                    run_id, link_id, "summary", summary_text,
                    "ai-summary", "haiku", result["tokens"], "summary"
                )

                self._complete_run(run_id, 1, total_tokens, model_used)
                return {
                    "link_id": link_id,
                    "summary": summary_text,
                    "tokens": total_tokens,
                    "cost_usd": result.get("estimated_cost_usd", 0),
                }

            raise ValueError("Generated summary was too short or empty")

        except Exception as e:
            self._complete_run(run_id, 0, total_tokens, model_used, str(e))
            return {
                "link_id": link_id,
                "summary": None,
                "error": str(e),
            }

    async def generate_summaries_batch(self, limit: int = 10) -> dict:
        """
        Generate summaries for links that need them.
        
        Uses prioritization to process most important links first.
        """
        # Get prioritized links needing summaries
        candidates = self._get_prioritized_links(limit, needs_summary=True, needs_comments=False)
        
        results = []
        total_tokens = 0
        total_cost = 0.0
        
        for link in candidates:
            result = await self.generate_summary(link["id"])
            results.append({
                "id": link["id"],
                "title": link.get("title", ""),
                "priority": link.get("_priority", 0),
                "summary": result.get("summary"),
                "error": result.get("error"),
            })
            
            total_tokens += result.get("tokens", 0)
            total_cost += result.get("cost_usd", 0)
            
            # Small delay between calls
            await asyncio.sleep(0.3)
        
        return {
            "processed": len(results),
            "successful": sum(1 for r in results if r.get("summary")),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "links": results,
        }

    # --------------------------------------------------------
    # Link Discovery
    # --------------------------------------------------------

    async def discover_links(self, topic: str = None, source: str = "web",
                             count: int = 5) -> dict:
        """
        Discover new links to add to the site.
        
        Args:
            topic: Search topic (for web search). If None, uses trending sources.
            source: "web" (Brave search), "hn" (Hacker News), "reddit"
            count: Target number of links to discover
        
        Returns:
            {"run_id": str, "discovered": int, "links": [...]}
        """
        params = {"topic": topic, "source": source, "count": count}
        run_id = self._create_run("discover", params)
        total_tokens = 0
        model_used = "haiku"

        try:
            candidates = []

            if source == "hn":
                # Fetch HN top stories
                hn_items = await self._fetch_hn_top(30)
                if hn_items:
                    prompt = discovery_hn_prompt(hn_items)
                    result = await self._call_claude(
                        prompt, "haiku", max_tokens=2048,
                        operation_type="discovery", run_id=run_id
                    )
                    total_tokens += result["tokens"]
                    parsed = self._parse_json_response(result["text"])
                    if parsed and isinstance(parsed, list):
                        candidates = parsed

            elif source == "web" and topic:
                # Brave search + Claude filter
                search_results = await self._brave_search(topic, count=15)
                if search_results:
                    prompt = discovery_filter_prompt(topic, search_results)
                    result = await self._call_claude(
                        prompt, "haiku", max_tokens=2048,
                        operation_type="discovery", run_id=run_id
                    )
                    total_tokens += result["tokens"]
                    parsed = self._parse_json_response(result["text"])
                    if parsed and isinstance(parsed, list):
                        candidates = parsed
                elif not self.brave_key:
                    # Fallback: ask Claude directly (less ideal but works)
                    prompt = f"""Suggest {count} interesting and recent links about: {topic}

Return a JSON array:
```json
[{{"url": "https://...", "title": "...", "reason": "...", "quality": 8}}]
```

Focus on well-known, real URLs from reputable sources. Return ONLY the JSON array."""
                    result = await self._call_claude(
                        prompt, "sonnet", max_tokens=2048,
                        operation_type="discovery", run_id=run_id
                    )
                    total_tokens += result["tokens"]
                    model_used = "sonnet"
                    parsed = self._parse_json_response(result["text"])
                    if parsed and isinstance(parsed, list):
                        candidates = parsed

            else:
                # Default: HN trending
                hn_items = await self._fetch_hn_top(30)
                if hn_items:
                    prompt = discovery_hn_prompt(hn_items)
                    result = await self._call_claude(
                        prompt, "haiku", max_tokens=2048,
                        operation_type="discovery", run_id=run_id
                    )
                    total_tokens += result["tokens"]
                    parsed = self._parse_json_response(result["text"])
                    if parsed and isinstance(parsed, list):
                        candidates = parsed

            # Sort by quality and take top N
            candidates.sort(key=lambda x: x.get("quality", 0), reverse=True)
            candidates = candidates[:count]

            # Add links to the site (check for duplicates)
            added_links = []
            for c in candidates:
                url = c.get("url", "").strip()
                if not url:
                    continue
                url = normalize_url(url)

                # Check if already exists
                existing = self.supabase.table("links").select("id").eq("url", url).execute()
                if existing.data:
                    continue

                # Insert new link
                insert_data = {
                    "url": url,
                    "title": c.get("title", ""),
                    "source": "ai-discovery",
                    "submitted_by": "ai-engine",
                    "description": c.get("reason", ""),
                }
                resp = self.supabase.table("links").insert(insert_data).execute()
                if resp.data:
                    link_id = resp.data[0]["id"]
                    added_links.append({
                        "id": link_id,
                        "url": url,
                        "title": c.get("title", ""),
                        "is_new": True,
                        "quality": c.get("quality", 0),
                    })

                    # Record in ai_generated_content
                    self._record_content(
                        run_id, link_id, "description",
                        c.get("reason", ""), "ai-discovery", model_used, 0
                    )

            self._complete_run(run_id, len(added_links), total_tokens, model_used)
            return {
                "run_id": run_id,
                "discovered": len(added_links),
                "links": added_links,
            }

        except Exception as e:
            self._complete_run(run_id, 0, total_tokens, model_used, str(e))
            return {"run_id": run_id, "discovered": 0, "links": [], "error": str(e)}

    # --------------------------------------------------------
    # Link Enrichment (Comments)
    # --------------------------------------------------------

    async def enrich_link(self, link_id: int, types: list[str] = None,
                          personas: list[str] = None) -> dict:
        """
        Enrich a single link with AI-generated content.
        
        Args:
            link_id: The link to enrich
            types: List of content types to generate.
                   Options: "description", "tags", "comments", "summary"
                   Default: ["description", "tags", "comments"]
            personas: List of persona IDs to use for comments.
                     If None, auto-selects based on content.
        
        Returns:
            {"run_id": str, "link_id": int, "generated": {...}}
        """
        if types is None:
            types = ["description", "tags", "comments"]

        params = {"link_id": link_id, "types": types, "personas": personas}
        run_id = self._create_run("enrich", params)
        total_tokens = 0
        model_used = "haiku"
        generated = {}

        try:
            # Fetch the link
            link_resp = self.supabase.table("links").select(
                "id, url, title, description, content, summary"
            ).eq("id", link_id).execute()

            if not link_resp.data:
                raise ValueError(f"Link {link_id} not found")

            link = link_resp.data[0]
            title = link.get("title") or ""
            url = link.get("url") or ""
            content = link.get("content") or link.get("description") or ""

            if not title and not content:
                raise ValueError(f"Link {link_id} has no title or content to analyze")

            # Get existing tags
            existing_tags = []
            try:
                from scratchpad_api import get_link_tags
                tags_data = get_link_tags(link_id)
                existing_tags = [t["name"] for t in tags_data]
            except Exception:
                pass

            # --- Generate Summary ---
            if "summary" in types and (not link.get("summary") or len(link.get("summary", "")) < 20):
                result = await self.generate_summary(link_id)
                if result.get("summary"):
                    generated["summary"] = result["summary"]
                    total_tokens += result.get("tokens", 0)

            # --- Generate Description ---
            if "description" in types and (not link.get("description") or len(link.get("description", "")) < 50):
                prompt = description_prompt(title, url, content)
                result = await self._call_claude(
                    prompt, "haiku", max_tokens=300,
                    operation_type="description", link_id=link_id, run_id=run_id
                )
                total_tokens += result["tokens"]

                desc = result["text"].strip()
                if desc and len(desc) > 20:
                    # Update the link's description
                    self.supabase.table("links").update(
                        {"description": desc}
                    ).eq("id", link_id).execute()

                    self._record_content(
                        run_id, link_id, "description", desc,
                        "ai-engine", "haiku", result["tokens"]
                    )
                    generated["description"] = desc

            # --- Generate Tags ---
            if "tags" in types:
                prompt = tag_suggestions_prompt(title, url, content, existing_tags)
                result = await self._call_claude(
                    prompt, "haiku", max_tokens=200,
                    operation_type="tags", link_id=link_id, run_id=run_id
                )
                total_tokens += result["tokens"]

                tags = self._parse_json_response(result["text"])
                if tags and isinstance(tags, list):
                    # Filter out existing tags
                    new_tags = [t for t in tags if t.lower().strip() not in
                               [e.lower() for e in existing_tags]]

                    if new_tags:
                        # Add tags to the link
                        for tag_name in new_tags:
                            slug = tag_name.lower().strip().replace(" ", "-")
                            if not slug:
                                continue
                            # Find or create tag
                            tag_resp = self.supabase.table("tags").select("id").eq("slug", slug).execute()
                            if tag_resp.data:
                                tag_id = tag_resp.data[0]["id"]
                            else:
                                new_tag = self.supabase.table("tags").insert(
                                    {"name": tag_name.strip(), "slug": slug}
                                ).execute()
                                tag_id = new_tag.data[0]["id"]

                            try:
                                self.supabase.table("link_tags").insert({
                                    "link_id": link_id,
                                    "tag_id": tag_id,
                                    "added_by": "ai-engine",
                                }).execute()
                            except Exception:
                                pass  # Already exists

                            self._record_content(
                                run_id, link_id, "tag", tag_name,
                                "ai-engine", "haiku", 0
                            )

                        generated["tags"] = new_tags

            # --- Generate Comments ---
            if "comments" in types:
                generated_comments = await self._generate_comments(
                    run_id, link_id, title, url, content, personas
                )
                if generated_comments:
                    generated["comments"] = generated_comments
                    for c in generated_comments:
                        total_tokens += c.get("tokens", 0)
                        if c.get("model") == "sonnet":
                            model_used = "sonnet"

            results_count = sum(1 for v in generated.values() if v)
            self._complete_run(run_id, results_count, total_tokens, model_used)

            return {
                "run_id": run_id,
                "link_id": link_id,
                "generated": generated,
            }

        except Exception as e:
            self._complete_run(run_id, 0, total_tokens, model_used, str(e))
            return {
                "run_id": run_id,
                "link_id": link_id,
                "generated": generated,
                "error": str(e),
            }

    async def _generate_comments(self, run_id: str, link_id: int,
                                  title: str, url: str, content: str,
                                  requested_personas: list[str] = None) -> list[dict]:
        """
        Generate comments from AI personas.
        
        Args:
            run_id: The current run ID
            link_id: Link to comment on
            title, url, content: Link content
            requested_personas: Specific personas to use, or None for auto-select
        
        Returns:
            List of generated comments with metadata
        """
        all_personas = self._get_personas()
        
        # Determine which personas to use
        if requested_personas:
            persona_ids = requested_personas
        else:
            persona_ids = self._pick_perspectives(title, content)
        
        generated_comments = []
        
        for persona_id in persona_ids:
            persona = all_personas.get(persona_id)
            if not persona:
                continue
            
            author = persona.get("author", f"ai-{persona_id}")
            
            # Check if we already have a comment from this persona
            existing_notes = self.supabase.table("notes").select("id").eq(
                "link_id", link_id
            ).eq("author", author).execute()

            if existing_notes.data:
                continue  # Skip — already commented

            # Build prompt
            prompt_fn = persona.get("prompt_fn")
            if not prompt_fn:
                prompt_fn = PROMPT_FUNCTIONS.get(persona_id)
            
            if not prompt_fn:
                continue
            
            prompt = prompt_fn(title, url, content)
            model_key = persona.get("model", "haiku")
            system_prompt = persona.get("system_prompt")
            
            result = await self._call_claude(
                prompt, model_key, max_tokens=800,
                system=system_prompt,
                operation_type="comment", link_id=link_id, run_id=run_id
            )

            comment_text = result["text"].strip()
            if comment_text and len(comment_text) > 30:
                # Add as a note
                self.supabase.table("notes").insert({
                    "link_id": link_id,
                    "author": author,
                    "text": comment_text,
                    "persona_id": persona_id,
                }).execute()

                self._record_content(
                    run_id, link_id, "comment", comment_text,
                    author, model_key, result["tokens"], persona_id
                )
                
                generated_comments.append({
                    "author": author,
                    "persona_id": persona_id,
                    "text": comment_text[:200] + "..." if len(comment_text) > 200 else comment_text,
                    "tokens": result["tokens"],
                    "model": model_key,
                })

        return generated_comments

    def _pick_perspectives(self, title: str, content: str) -> list[str]:
        """Pick which comment perspectives to use based on content type."""
        text = f"{title} {content}".lower()

        perspectives = []  # Don't always include summary as a comment

        # Technical content gets technical analysis
        tech_keywords = ["algorithm", "api", "code", "framework", "model", "architecture",
                         "system", "performance", "benchmark", "protocol", "database",
                         "machine learning", "neural", "compiler", "runtime", "kubernetes",
                         "docker", "rust", "python", "javascript", "typescript"]
        if any(kw in text for kw in tech_keywords):
            perspectives.append("technical")

        # Business/product content gets business analysis
        biz_keywords = ["startup", "funding", "market", "revenue", "company", "product",
                        "launch", "acquisition", "ipo", "valuation", "growth", "enterprise",
                        "series a", "seed round", "venture", "profit"]
        if any(kw in text for kw in biz_keywords):
            perspectives.append("business")

        # Controversial or opinion content gets contrarian view
        opinion_keywords = ["should", "must", "need to", "wrong", "right", "best", "worst",
                           "always", "never", "future of", "death of", "end of", "revolution",
                           "controversial", "debate", "opinion"]
        if any(kw in text for kw in opinion_keywords):
            perspectives.append("contrarian")

        # Educational/tutorial content gets curious newcomer
        edu_keywords = ["how to", "tutorial", "guide", "introduction", "beginner",
                        "learn", "explained", "basics", "fundamentals"]
        if any(kw in text for kw in edu_keywords):
            perspectives.append("curious")

        # Historical/retrospective content gets historian
        hist_keywords = ["history", "retrospective", "years ago", "evolution",
                         "origin", "early days", "pioneered", "invented"]
        if any(kw in text for kw in hist_keywords):
            perspectives.append("historian")

        # If nothing specific matched, add technical + one other
        if len(perspectives) == 0:
            perspectives = ["technical"]

        # Add a second perspective if we only have one
        if len(perspectives) == 1:
            if "technical" not in perspectives:
                perspectives.append("technical")
            else:
                perspectives.append("contrarian")

        # Cap at 3 perspectives to control costs
        return perspectives[:3]

    # --------------------------------------------------------
    # Batch Enrichment
    # --------------------------------------------------------

    async def enrich_batch(self, limit: int = 10,
                           types: list[str] = None) -> dict:
        """
        Find links needing enrichment and process them.
        
        Uses priority scoring to process most important links first.
        
        Prioritizes:
        1. Popular links (higher engagement/votes)
        2. Recent links
        3. Links missing content
        
        Args:
            limit: Max links to process
            types: Content types to generate (default: all)
        
        Returns:
            {"enriched": int, "skipped": int, "links": [...]}
        """
        if types is None:
            types = ["description", "tags", "comments"]

        # Use prioritization system
        candidates = self._get_prioritized_links(
            limit=limit,
            needs_summary="summary" in types,
            needs_comments="comments" in types,
        )

        results = []
        for link in candidates:
            needs = []
            
            if "description" in types and (not link.get("description") or len(link.get("description", "")) < 50):
                needs.append("description")
            if "tags" in types:
                # Check if has any tags
                tags = self.supabase.table("link_tags").select("link_id, tag_id").eq(
                    "link_id", link["id"]
                ).limit(1).execute()
                if not tags.data:
                    needs.append("tags")
            if "comments" in types:
                # Check if has any AI comments
                notes = self.supabase.table("notes").select("link_id, author").eq(
                    "link_id", link["id"]
                ).ilike("author", "ai-%").limit(1).execute()
                if not notes.data:
                    needs.append("comments")
            if "summary" in types and not link.get("summary"):
                needs.append("summary")

            if not needs:
                continue

            result = await self.enrich_link(link["id"], types=needs)
            results.append({
                "id": link["id"],
                "title": link.get("title", ""),
                "priority": link.get("_priority", 0),
                "generated": list(result.get("generated", {}).keys()),
                "error": result.get("error"),
            })

            # Small delay to avoid hammering the API
            await asyncio.sleep(0.5)

        enriched = sum(1 for r in results if not r.get("error"))
        
        return {
            "enriched": enriched,
            "total_processed": len(results),
            "links": results,
        }

    # --------------------------------------------------------
    # Stats & Metrics
    # --------------------------------------------------------

    async def get_run_stats(self) -> dict:
        """Get aggregate statistics about AI engine runs."""
        # Total runs by type
        all_runs = self.supabase.table("ai_runs").select(
            "type, status, results_count, tokens_used, created_at"
        ).execute()

        runs = all_runs.data or []

        total_runs = len(runs)
        completed = [r for r in runs if r["status"] == "completed"]
        discover_runs = [r for r in completed if r["type"] == "discover"]
        enrich_runs = [r for r in completed if r["type"] == "enrich"]

        total_discovered = sum(r.get("results_count", 0) for r in discover_runs)
        total_enriched = sum(r.get("results_count", 0) for r in enrich_runs)
        total_tokens = sum(r.get("tokens_used", 0) for r in completed)

        # Content breakdown
        content_resp = self.supabase.table("ai_generated_content").select(
            "content_type, model_used, persona_id"
        ).execute()
        content = content_resp.data or []

        content_by_type = {}
        model_usage = {}
        persona_usage = {}
        for c in content:
            ct = c.get("content_type", "unknown")
            content_by_type[ct] = content_by_type.get(ct, 0) + 1
            m = c.get("model_used", "unknown")
            model_usage[m] = model_usage.get(m, 0) + 1
            p = c.get("persona_id")
            if p:
                persona_usage[p] = persona_usage.get(p, 0) + 1

        last_run = max((r.get("created_at", "") for r in runs), default=None) if runs else None

        # Get token usage stats
        token_stats = await self.get_token_usage_stats(days=30)

        return {
            "total_runs": total_runs,
            "completed_runs": len(completed),
            "failed_runs": sum(1 for r in runs if r["status"] == "failed"),
            "total_discovered": total_discovered,
            "total_enriched": total_enriched,
            "total_tokens": total_tokens,
            "content_by_type": content_by_type,
            "model_usage": model_usage,
            "persona_usage": persona_usage,
            "avg_per_discover_run": round(total_discovered / max(len(discover_runs), 1), 1),
            "avg_per_enrich_run": round(total_enriched / max(len(enrich_runs), 1), 1),
            "last_run": last_run,
            "token_usage_30d": token_stats,
        }

    async def get_runs(self, limit: int = 20, run_type: str = None) -> list[dict]:
        """Get recent AI engine runs."""
        query = self.supabase.table("ai_runs").select("*").order(
            "created_at", desc=True
        ).limit(limit)

        if run_type:
            query = query.eq("type", run_type)

        resp = query.execute()
        return resp.data or []

    async def get_personas(self) -> list[dict]:
        """Get all configured personas with usage stats."""
        personas = self._get_personas(force_refresh=True)
        
        # Get usage counts
        content_resp = self.supabase.table("ai_generated_content").select(
            "persona_id"
        ).execute()
        
        usage_counts = {}
        for c in (content_resp.data or []):
            p = c.get("persona_id")
            if p:
                usage_counts[p] = usage_counts.get(p, 0) + 1
        
        result = []
        for pid, persona in personas.items():
            result.append({
                "id": pid,
                "author": persona.get("author"),
                "model": persona.get("model"),
                "description": persona.get("description"),
                "priority": persona.get("priority"),
                "has_custom_prompt": bool(persona.get("system_prompt")),
                "usage_count": usage_counts.get(pid, 0),
            })
        
        result.sort(key=lambda x: x.get("priority", 0), reverse=True)
        return result
