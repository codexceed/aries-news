"""JSON API router exposing news search over the gnews.io backend."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_news_service
from app.schemas.article import ArticleBase
from app.services.news import NewsService, NewsServiceError

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/search")
async def search_news(
    query: Annotated[str, Query(alias="q", description="Free-text search query.")],
    service: Annotated[NewsService, Depends(get_news_service)],
    max_results: Annotated[
        int,
        Query(alias="max", ge=1, le=50, description="Maximum number of articles."),
    ] = 10,
) -> list[ArticleBase]:
    """Search for news articles matching ``query``.

    Args:
        query: The free-text search query. Must not be blank.
        service: The injected news service.
        max_results: The maximum number of articles to return (1..50).

    Returns:
        The matching articles.

    Raises:
        HTTPException: ``400`` if ``query`` is blank, or ``502`` if the upstream
            news provider fails.
    """
    if not query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'q' must not be blank.",
        )

    try:
        return await service.search(query, max_results=max_results)
    except NewsServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"News provider unavailable: {exc}",
        ) from exc
