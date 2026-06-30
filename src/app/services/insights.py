"""Application service orchestrating the insight repository and the job queue.

:class:`InsightsService` is the boundary the API talks to: it turns an analysis
request into a persisted pending job and wakes the worker, exposes read access to
insights, and passes through the live SSE subscription that combines the current
database state with subsequent status changes.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.core.enums import JobStatus
from app.models import Insight
from app.repositories import insights as repo
from app.schemas import ArticleBase, InsightRead
from app.services.jobs import JobQueue, job_queue

logger = logging.getLogger(__name__)

_TERMINAL = (JobStatus.DONE, JobStatus.FAILED)


class InsightsService:
    """Coordinates persistence and background processing of insights."""

    def __init__(self, queue: JobQueue | None = None) -> None:
        """Initialise the service.

        Args:
            queue: Optional job queue override. Defaults to the shared
                process-wide :data:`~app.services.jobs.job_queue`.
        """
        self._queue = queue or job_queue

    @property
    def queue(self) -> JobQueue:
        """Return the underlying job queue.

        Returns:
            The :class:`~app.services.jobs.JobQueue` this service drives.
        """
        return self._queue

    async def request_analysis(self, session: AsyncSession, article: ArticleBase) -> Insight:
        """Ensure a pending insight exists for an article and wake the worker.

        Idempotent: an article already analyzed (or in progress) returns its
        existing insight without re-queuing; only genuinely pending work nudges
        the worker loop.

        Args:
            session: The request-scoped database session.
            article: The article to analyze.

        Returns:
            The existing or newly created :class:`Insight`.
        """
        insight = await repo.get_or_create_pending_insight(session, article)
        if insight.status == JobStatus.PENDING:
            self._queue.notify()
            logger.info("queued insight %d for analysis", insight.id)
        return insight

    async def get(self, session: AsyncSession, insight_id: int) -> Insight | None:
        """Return a single insight by id.

        Args:
            session: The request-scoped database session.
            insight_id: The insight identifier.

        Returns:
            The :class:`Insight` or ``None`` if it does not exist.
        """
        return await repo.get(session, insight_id)

    async def list_all(self, session: AsyncSession) -> list[Insight]:
        """Return all insights, newest first.

        Args:
            session: The request-scoped database session.

        Returns:
            Every :class:`Insight` ordered newest first.
        """
        return await repo.list_all(session)

    async def subscribe(self, insight_id: int) -> AsyncIterator[InsightRead]:
        """Stream an insight's current state followed by live status changes.

        Registers for updates before reading the database so no change is missed
        in the gap, emits the current state immediately, and then forwards each
        published update until the insight reaches a terminal state.

        Args:
            insight_id: The insight to stream.

        Yields:
            The current :class:`InsightRead`, then one per status change, ending
            after ``DONE``/``FAILED``.
        """
        queue = self._queue.subscribe_queue(insight_id)
        try:
            async with SessionFactory() as session:
                current = await repo.get(session, insight_id)
            if current is None:
                return
            snapshot = InsightRead.model_validate(current)
            yield snapshot
            if snapshot.status in _TERMINAL:
                return
            while True:
                insight = await queue.get()
                yield insight
                if insight.status in _TERMINAL:
                    return
        finally:
            self._queue.unsubscribe(insight_id, queue)


# Process-wide service instance shared by the API layer.
insights_service = InsightsService()
