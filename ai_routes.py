"""
AI Content Engine — FastAPI Routes

Mount these routes on the main FastAPI app to expose the AI engine
as HTTP endpoints.

Usage in main.py:
    from ai_routes import create_ai_router
    ai_router = create_ai_router(supabase)
    app.include_router(ai_router)
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from ai_engine import AIEngine


# ============================================================
# Request Models
# ============================================================

class DiscoverRequest(BaseModel):
    topic: Optional[str] = None
    source: str = "web"  # "web", "hn", "reddit"
    count: int = 5


class EnrichRequest(BaseModel):
    limit: int = 10
    types: Optional[List[str]] = None  # ["description", "tags", "comments", "summary"]


class EnrichSingleRequest(BaseModel):
    types: Optional[List[str]] = None
    personas: Optional[List[str]] = None  # Specific personas to use for comments


class SummaryBatchRequest(BaseModel):
    limit: int = 10


class PersonaUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    model: Optional[str] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = None


# ============================================================
# Router Factory
# ============================================================

def create_ai_router(supabase_client, anthropic_api_key: str = None,
                     brave_api_key: str = None, vectorize_fn=None) -> APIRouter:
    """Create and return the AI engine router with dependencies injected."""

    router = APIRouter(prefix="/api/ai", tags=["ai-engine"])
    engine = AIEngine(
        supabase_client,
        anthropic_api_key=anthropic_api_key,
        brave_api_key=brave_api_key,
        vectorize_fn=vectorize_fn,
    )

    # --------------------------------------------------------
    # Discovery
    # --------------------------------------------------------

    @router.post("/discover")
    async def ai_discover(body: DiscoverRequest, background_tasks: BackgroundTasks):
        """
        Discover new links to add to the site.
        
        Runs in the background — returns immediately with a run_id.
        Check /api/ai/runs/{run_id} for results.
        """
        if body.count > 20:
            raise HTTPException(400, "count must be <= 20")

        # For small counts, run synchronously for immediate feedback
        if body.count <= 5:
            result = await engine.discover_links(
                topic=body.topic,
                source=body.source,
                count=body.count,
            )
            return result

        # For larger counts, run in background
        async def _run():
            await engine.discover_links(
                topic=body.topic,
                source=body.source,
                count=body.count,
            )

        background_tasks.add_task(_run)
        return {
            "status": "started",
            "message": f"Discovering {body.count} links about '{body.topic or 'trending'}' in background",
        }

    # --------------------------------------------------------
    # Summary Generation
    # --------------------------------------------------------

    @router.post("/summary/{link_id}")
    async def ai_generate_summary(link_id: int):
        """Generate a summary for a specific link."""
        result = await engine.generate_summary(link_id)
        
        if result.get("error"):
            raise HTTPException(400, result["error"])
        
        return result

    @router.post("/summaries")
    async def ai_generate_summaries_batch(body: SummaryBatchRequest, background_tasks: BackgroundTasks):
        """
        Generate summaries for links that need them.
        
        Uses prioritization to process most important links first.
        """
        if body.limit > 50:
            raise HTTPException(400, "limit must be <= 50")

        if body.limit <= 5:
            result = await engine.generate_summaries_batch(limit=body.limit)
            return result

        async def _run():
            await engine.generate_summaries_batch(limit=body.limit)

        background_tasks.add_task(_run)
        return {
            "status": "started",
            "message": f"Generating summaries for up to {body.limit} links in background",
        }

    # --------------------------------------------------------
    # Enrichment
    # --------------------------------------------------------

    @router.post("/enrich")
    async def ai_enrich_batch(body: EnrichRequest, background_tasks: BackgroundTasks):
        """
        Enrich existing links that need descriptions, tags, comments, or summaries.
        
        Uses prioritization to process most important links first.
        Runs in the background for batches > 3.
        """
        if body.limit > 50:
            raise HTTPException(400, "limit must be <= 50")

        if body.limit <= 3:
            result = await engine.enrich_batch(
                limit=body.limit,
                types=body.types,
            )
            return result

        async def _run():
            await engine.enrich_batch(
                limit=body.limit,
                types=body.types,
            )

        background_tasks.add_task(_run)
        return {
            "status": "started",
            "message": f"Enriching up to {body.limit} links in background",
        }

    @router.post("/enrich/{link_id}")
    async def ai_enrich_single(link_id: int, body: EnrichSingleRequest = None):
        """
        Enrich a specific link with AI-generated content.
        
        Optionally specify which content types to generate and which personas to use.
        """
        types = body.types if body else None
        personas = body.personas if body else None
        result = await engine.enrich_link(link_id, types=types, personas=personas)

        if result.get("error"):
            raise HTTPException(400, result["error"])

        return result

    # --------------------------------------------------------
    # Personas
    # --------------------------------------------------------

    @router.get("/personas")
    async def ai_personas():
        """Get all configured AI personas with usage stats."""
        return {"personas": await engine.get_personas()}

    @router.get("/personas/{persona_id}")
    async def ai_persona_detail(persona_id: str):
        """Get details for a specific persona."""
        personas = engine._get_personas()
        persona = personas.get(persona_id)
        
        if not persona:
            raise HTTPException(404, "Persona not found")
        
        # Get usage count
        content_resp = supabase_client.table("ai_generated_content").select(
            "id"
        ).eq("persona_id", persona_id).execute()
        
        return {
            "id": persona_id,
            "author": persona.get("author"),
            "model": persona.get("model"),
            "description": persona.get("description"),
            "priority": persona.get("priority"),
            "has_system_prompt": bool(persona.get("system_prompt")),
            "usage_count": len(content_resp.data or []),
        }

    @router.put("/personas/{persona_id}")
    async def ai_persona_update(persona_id: str, body: PersonaUpdateRequest):
        """Update a persona's configuration."""
        update_data = {}
        if body.name is not None:
            update_data["name"] = body.name
        if body.description is not None:
            update_data["description"] = body.description
        if body.system_prompt is not None:
            update_data["system_prompt"] = body.system_prompt
        if body.user_prompt_template is not None:
            update_data["user_prompt_template"] = body.user_prompt_template
        if body.model is not None:
            update_data["model"] = body.model
        if body.is_active is not None:
            update_data["is_active"] = body.is_active
        if body.priority is not None:
            update_data["priority"] = body.priority

        if not update_data:
            raise HTTPException(400, "No fields to update")

        try:
            # Check if persona exists in DB
            existing = supabase_client.table("ai_personas").select("id").eq("id", persona_id).execute()
            
            if existing.data:
                supabase_client.table("ai_personas").update(update_data).eq("id", persona_id).execute()
            else:
                # Create new entry
                update_data["id"] = persona_id
                supabase_client.table("ai_personas").insert(update_data).execute()
            
            # Clear cache
            engine._personas_cache = None
            
            return {"ok": True, "persona_id": persona_id}
        except Exception as e:
            raise HTTPException(500, str(e))

    # --------------------------------------------------------
    # Token Usage
    # --------------------------------------------------------

    @router.get("/token-usage")
    async def ai_token_usage(days: int = 30):
        """Get token usage statistics for the specified period."""
        if days > 365:
            days = 365
        return await engine.get_token_usage_stats(days=days)

    # --------------------------------------------------------
    # Stats & Runs
    # --------------------------------------------------------

    @router.get("/stats")
    async def ai_stats():
        """Get aggregate statistics about AI engine operations."""
        return await engine.get_run_stats()

    @router.get("/runs")
    async def ai_runs(limit: int = 20, type: Optional[str] = None):
        """Get recent AI engine runs."""
        if limit > 100:
            limit = 100
        runs = await engine.get_runs(limit=limit, run_type=type)
        return {"runs": runs}

    @router.get("/runs/{run_id}")
    async def ai_run_detail(run_id: str):
        """Get details of a specific run including generated content."""
        run_resp = supabase_client.table("ai_runs").select("*").eq("id", run_id).execute()
        if not run_resp.data:
            raise HTTPException(404, "Run not found")

        content_resp = supabase_client.table("ai_generated_content").select(
            "*"
        ).eq("run_id", run_id).execute()

        # Also get token usage for this run
        token_resp = supabase_client.table("ai_token_usage").select(
            "*"
        ).eq("run_id", run_id).execute()

        return {
            "run": run_resp.data[0],
            "content": content_resp.data or [],
            "token_usage": token_resp.data or [],
        }

    # --------------------------------------------------------
    # Health Check
    # --------------------------------------------------------

    @router.get("/health")
    async def ai_health():
        """Check if the AI engine is properly configured."""
        has_anthropic = bool(engine.api_key)
        has_brave = bool(engine.brave_key)

        return {
            "status": "ok" if has_anthropic else "degraded",
            "anthropic_api": "configured" if has_anthropic else "missing",
            "brave_search": "configured" if has_brave else "missing (discovery will use HN fallback)",
        }

    return router
