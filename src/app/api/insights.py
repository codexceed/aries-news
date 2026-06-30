"""HTTP API for AI insights: request analysis, read results, and stream progress.

Routes are mounted under ``/api/insights``. Writes and point reads use the
request-scoped database session; the streaming route uses Server-Sent Events to
push live status changes. The module also exposes :func:`start_workers` /
:func:`stop_workers` for the application lifespan to drive the background queue.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.db import get_session
from app.schemas import ArticleBase, InsightRead
from app.services.insights import insights_service
from app.services.jobs import job_queue

router = APIRouter(prefix="/api/insights", tags=["insights"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/", status_code=status.HTTP_202_ACCEPTED, response_model=InsightRead)
async def create_insight(article: ArticleBase, session: SessionDep) -> InsightRead:
    """Request analysis for an article and return its (pending) insight.

    Idempotent: posting the same article again returns its existing insight.

    Args:
        article: The article to analyze.
        session: The request-scoped database session.

    Returns:
        The created or existing insight, with HTTP ``202 Accepted``.
    """
    insight = await insights_service.request_analysis(session, article)
    return InsightRead.model_validate(insight)


@router.get("/", response_model=list[InsightRead])
async def list_insights(session: SessionDep) -> list[InsightRead]:
    """List all insights, newest first (the AI Insights page data).

    Args:
        session: The request-scoped database session.

    Returns:
        Every insight ordered newest first.
    """
    insights = await insights_service.list_all(session)
    return [InsightRead.model_validate(insight) for insight in insights]


@router.get("/{insight_id}", response_model=InsightRead)
async def get_insight(insight_id: int, session: SessionDep) -> InsightRead:
    """Return a single insight by id.

    Args:
        insight_id: The insight identifier.
        session: The request-scoped database session.

    Returns:
        The matching insight.

    Raises:
        HTTPException: ``404`` if no insight with that id exists.
    """
    insight = await insights_service.get(session, insight_id)
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="insight not found")
    return InsightRead.model_validate(insight)


@router.get("/{insight_id}/stream")
async def stream_insight(insight_id: int) -> EventSourceResponse:
    """Stream an insight's status as Server-Sent Events until it is terminal.

    Emits the current state immediately, then one event per status change, and
    closes once the insight reaches ``DONE``/``FAILED``. Each event's ``data`` is
    the :class:`InsightRead` JSON.

    Args:
        insight_id: The insight to stream.

    Returns:
        An SSE response yielding insight snapshots.
    """

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        async for insight in insights_service.subscribe(insight_id):
            yield {"data": insight.model_dump_json()}

    return EventSourceResponse(event_stream())


async def start_workers() -> None:
    """Start the background insight worker (call from the app lifespan startup)."""
    await job_queue.start()


async def stop_workers() -> None:
    """Stop the background insight worker (call from the app lifespan shutdown)."""
    await job_queue.stop()
