"""Search router for full-text search across meeting content."""

from fastapi import APIRouter, Query

from app.services.search_service import SearchService


def create_search_router(search_service: SearchService) -> APIRouter:
    router = APIRouter(tags=["search"])

    @router.get("/api/search")
    async def search_meetings(
        q: str = Query(..., min_length=2, description="Search query"),
        limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    ):
        """Search across all meeting content.
        
        Searches title, summary, transcript, attendees, user notes, manual notes, and chat.
        Returns matches with snippets showing context around the match.
        """
        results = search_service.search_all_fields(q, limit=limit)
        return [result.to_dict() for result in results]

    return router
