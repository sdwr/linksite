"""
AI Content Engine â€” Core Logic

Integrates with the Linksite FastAPI app to discover and enrich links
using Claude AI models. All operations are tracked in ai_runs and
ai_generated_content tables.

Usage:
    from ai_engine import AIEngine
    engine = AIEngine(supabase_client)
    
    # Discover new links
    result = await engine.discover_links(topic="AI safety", count=5)
    
    # Enrich a single link
    result = await engine.enrich_link(link_id=123)
    
    # Batch enrich
    result = await engine.enrich_batch(limit=10)
"""

import os
import json
import asyncio
import httpx
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from prompts import (
    discovery_filter_prompt,
    discovery_hn_prompt,
    description_prompt,
    tag_suggestions_prompt,
    summary_prompt,
    PERSONAS,
)

# ============================================================
# Model Configuration
# ============================================================

MODELS = {
    "haiku": "claude-3-5-haiku-20241022",
    "sonnet": "claude-sonnet-4-20250514",
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
    # Claude API
    # --------------------------------------------------------

    async def _call_claude(self, prompt: str, model_key: str = "haiku",
                           max_tokens: int = 1024, system: str = None) -> dict:
        """Call Claude API and return response + token usage."""
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

        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        return {"text": text, "tokens": tokens, "model": model_key}

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
                        tokens_used: int = 0):
        """Record a piece of generated content."""
        self.supabase.table("ai_generated_content").insert({
            "run_id": run_id,
            "link_id": link_id,
            "content_type": content_type,
            "content": content,
            "author": author,
            "model_used": model_used,
            "tokens_used": tokens_used,
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
                    result = await self._call_claude(prompt, "haiku", max_tokens=2048)
                    total_tokens += result["tokens"]
                    parsed = self._parse_json_response(result["text"])
                    if parsed and isinstance(parsed, list):
                        candidates = parsed

            elif source == "web" and topic:
                # Brave search + Claude filter
                search_results = await self._brave_search(topic, count=15)
                if search_results:
                    prompt = discovery_filter_prompt(topic, search_results)
                    result = await self._call_claude(prompt, "haiku", max_tokens=2048)
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
                    result = await self._call_claude(prompt, "sonnet", max_tokens=2048)
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
                    result = await self._call_claude(prompt, "haiku", max_tokens=2048)
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
    # Link Enrichment
    # --------------------------------------------------------

    async def enrich_link(self, link_id: int,
                          types: list[str] = None) -> dict:
        """
        Enrich a single link with AI-generated content.
        
        Args:
            link_id: The link to enrich
            types: List of content types to generate.
                   Options: "description", "tags", "comments", "summary"
                   Default: all types
        
        Returns:
            {"run_id": str, "link_id": int, "generated": {...}}
        """
        if types is None:
            types = ["description", "tags", "comments"]

        params = {"link_id": link_id, "types": types}
        run_id = self._create_run("enrich", params)
        total_tokens = 0
        model_used = "haiku"
        generated = {}

        try:
            # Fetch the link
            link_resp = self.supabase.table("links").select(
                "id, url, title, description, content"
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

            # --- Generate Description ---
            if "description" in types and (not link.get("description") or len(link.get("description", "")) < 50):
                prompt = description_prompt(title, url, content)
                result = await self._call_claude(prompt, "haiku", max_tokens=300)
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
                result = await self._call_claude(prompt, "haiku", max_tokens=200)
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
                generated_comments = []

                # Pick 1-2 comment perspectives based on content type
                perspectives = self._pick_perspectives(title, content)

                for persona_key in perspectives:
                    persona = PERSONAS.get(persona_key)
                    if not persona:
                        continue

                    # Check if we already have a comment from this persona
                    existing_notes = self.supabase.table("notes").select("id").eq(
                        "link_id", link_id
                    ).eq("author", persona["author"]).execute()

                    if existing_notes.data:
                        continue  # Skip â€” already commented

                    prompt = persona["prompt_fn"](title, url, content)
                    model_key = persona.get("model", "haiku")
                    result = await self._call_claude(prompt, model_key, max_tokens=800)
                    total_tokens += result["tokens"]
                    if model_key in ("sonnet",):
                        model_used = "sonnet"

                    comment_text = result["text"].strip()
                    if comment_text and len(comment_text) > 30:
                        # Add as a note
                        self.supabase.table("notes").insert({
                            "link_id": link_id,
                            "author": persona["author"],
                            "text": comment_text,
                        }).execute()

                        self._record_content(
                            run_id, link_id, "comment", comment_text,
                            persona["author"], model_key, result["tokens"]
                        )
                        generated_comments.append({
                            "author": persona["author"],
                            "text": comment_text[:200] + "..." if len(comment_text) > 200 else comment_text,
                        })

                if generated_comments:
                    generated["comments"] = generated_comments

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

    def _pick_perspectives(self, title: str, content: str) -> list[str]:
        """Pick which comment perspectives to use based on content type."""
        text = f"{title} {content}".lower()

        perspectives = ["summary"]  # Always include a summary

        # Technical content gets technical analysis
        tech_keywords = ["algorithm", "api", "code", "framework", "model", "architecture",
                         "system", "performance", "benchmark", "protocol", "database",
                         "machine learning", "neural", "compiler", "runtime"]
        if any(kw in text for kw in tech_keywords):
            perspectives.append("technical")

        # Business/product content gets business analysis
        biz_keywords = ["startup", "funding", "market", "revenue", "company", "product",
                        "launch", "acquisition", "ipo", "valuation", "growth", "enterprise"]
        if any(kw in text for kw in biz_keywords):
            perspectives.append("business")

        # Controversial or opinion content gets contrarian view
        opinion_keywords = ["should", "must", "need to", "wrong", "right", "best", "worst",
                           "always", "never", "future of", "death of", "end of", "revolution"]
        if any(kw in text for kw in opinion_keywords):
            perspectives.append("contrarian")

        # If we only have summary, add at least one analysis
        if len(perspectives) == 1:
            perspectives.append("technical")

        # Cap at 3 perspectives to control costs
        return perspectives[:3]

    # --------------------------------------------------------
    # Batch Enrichment
    # --------------------------------------------------------

    async def enrich_batch(self, limit: int = 10,
                           types: list[str] = None) -> dict:
        """
        Find links needing enrichment and process them.
        
        Prioritizes:
        1. Links with no description
        2. Links with no tags
        3. Links with no AI comments
        4. Most recently added first
        
        Args:
            limit: Max links to process
            types: Content types to generate (default: all)
        
        Returns:
            {"run_id": str, "enriched": int, "skipped": int, "links": [...]}
        """
        if types is None:
            types = ["description", "tags", "comments"]

        # Find links that need enrichment
        # Strategy: get recent links and check what they're missing
        links_resp = self.supabase.table("links").select(
            "id, url, title, description, content, source"
        ).neq("source", "auto-parent").order(
            "created_at", desc=True
        ).limit(limit * 3).execute()  # Fetch extra to account for skips

        candidates = []
        for link in (links_resp.data or []):
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

            if needs:
                candidates.append({"link": link, "needs": needs})

        # Process up to `limit` candidates
        candidates = candidates[:limit]

        results = []
        for c in candidates:
            result = await self.enrich_link(
                c["link"]["id"],
                types=c["needs"],
            )
            results.append({
                "id": c["link"]["id"],
                "title": c["link"].get("title", ""),
                "generated": list(result.get("generated", {}).keys()),
                "error": result.get("error"),
            })

            # Small delay to avoid hammering the API
            await asyncio.sleep(0.5)

        enriched = sum(1 for r in results if not r.get("error"))
        skipped = len(links_resp.data or []) - len(candidates)

        return {
            "enriched": enriched,
            "skipped": skipped,
            "total_checked": len(links_resp.data or []),
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
            "content_type, model_used"
        ).execute()
        content = content_resp.data or []

        content_by_type = {}
        model_usage = {}
        for c in content:
            ct = c.get("content_type", "unknown")
            content_by_type[ct] = content_by_type.get(ct, 0) + 1
            m = c.get("model_used", "unknown")
            model_usage[m] = model_usage.get(m, 0) + 1

        last_run = max((r.get("created_at", "") for r in runs), default=None) if runs else None

        return {
            "total_runs": total_runs,
            "completed_runs": len(completed),
            "failed_runs": sum(1 for r in runs if r["status"] == "failed"),
            "total_discovered": total_discovered,
            "total_enriched": total_enriched,
            "total_tokens": total_tokens,
            "content_by_type": content_by_type,
            "model_usage": model_usage,
            "avg_per_discover_run": round(total_discovered / max(len(discover_runs), 1), 1),
            "avg_per_enrich_run": round(total_enriched / max(len(enrich_runs), 1), 1),
            "last_run": last_run,
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
