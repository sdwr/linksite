"""
AI Content Engine â€” FastAPI Routes

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
    types: Optional[List[str]] = None  # ["description", "tags", "comments"]


class EnrichSingleRequest(BaseModel):
    types: Optional[List[str]] = None


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
        
        Runs in the background â€” returns immediately with a run_id.
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
    # Enrichment
    # --------------------------------------------------------

    @router.post("/enrich")
    async def ai_enrich_batch(body: EnrichRequest, background_tasks: BackgroundTasks):
        """
        Enrich existing links that need descriptions, tags, or comments.
        
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
        """Enrich a specific link with AI-generated content."""
        types = body.types if body else None
        result = await engine.enrich_link(link_id, types=types)

        if result.get("error"):
            raise HTTPException(400, result["error"])

        return result

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

        return {
            "run": run_resp.data[0],
            "content": content_resp.data or [],
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
