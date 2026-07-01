"""In-process asyncio worker that drains pending insight jobs.

The :class:`JobQueue` runs a single loop coroutine that repeatedly claims the next
pending insight (``FOR UPDATE SKIP LOCKED``) and processes it in a child task,
bounding concurrent OpenAI calls with a semaphore. Each status change is broadcast
to per-insight subscribers so the SSE endpoint can stream live progress.

The broadcaster is **per-process**: subscribers only see events produced by the
worker running in the same process. That is correct for a single-instance
deployment and a known limitation under horizontal scaling, where a shared
pub/sub bus (or polling) would be required instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.db import SessionFactory
from app.models import Article
from app.repositories import insights as repo
from app.schemas import ArticleBase, InsightRead
from app.services.openai_client import analyze_article

logger = logging.getLogger(__name__)

_IDLE_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class _ClaimedJob:
    """A claimed insight plus the article snapshot needed to process it."""

    insight_id: int
    article: ArticleBase
    running: InsightRead


class JobQueue:
    """An in-process worker pool for AI insight jobs with SSE broadcasting.

    A single loop coroutine claims jobs and dispatches each to a child task gated
    by a concurrency semaphore. Status changes are published to per-insight
    :class:`asyncio.Queue` subscribers. Worker-owned database work uses the shared
    :data:`~app.core.db.SessionFactory`, never the request-scoped session.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialise the queue.

        Args:
            settings: Optional settings override. Defaults to
                :func:`~app.core.config.get_settings`.
        """
        self._settings = settings or get_settings()
        self._semaphore = asyncio.Semaphore(self._settings.insights_max_concurrency)
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._children: set[asyncio.Task[None]] = set()
        self._subscribers: dict[int, set[asyncio.Queue[InsightRead]]] = {}

    async def start(self) -> None:
        """Reap orphaned jobs once, then start the worker loop.

        Idempotent: calling it while already running is a no-op.
        """
        if self._loop_task is not None:
            return
        async with SessionFactory() as session:
            reaped = await repo.reap_stale(session, self._settings.insights_stale_after_seconds)
        if reaped:
            logger.info("reaped %d stale insight(s) on startup", reaped)
        self._loop_task = asyncio.create_task(self._run_loop(), name="insights-worker-loop")
        logger.info(
            "JobQueue started (max_concurrency=%d)", self._settings.insights_max_concurrency
        )

    async def stop(self) -> None:
        """Cancel the worker loop and any in-flight child tasks cleanly."""
        if self._loop_task is None:
            return
        self._loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._loop_task
        self._loop_task = None

        for task in list(self._children):
            task.cancel()
        if self._children:
            await asyncio.gather(*self._children, return_exceptions=True)
        self._children.clear()
        logger.info("JobQueue stopped")

    def notify(self) -> None:
        """Wake the worker loop after a new job has been created."""
        self._wake.set()

    def subscribe_queue(self, insight_id: int) -> asyncio.Queue[InsightRead]:
        """Register and return a queue receiving updates for ``insight_id``.

        Args:
            insight_id: The insight to receive status changes for.

        Returns:
            A queue onto which each subsequent :class:`InsightRead` is pushed.
        """
        queue: asyncio.Queue[InsightRead] = asyncio.Queue()
        self._subscribers.setdefault(insight_id, set()).add(queue)
        return queue

    def unsubscribe(self, insight_id: int, queue: asyncio.Queue[InsightRead]) -> None:
        """Deregister a previously registered subscriber queue.

        Args:
            insight_id: The insight the queue was subscribed to.
            queue: The queue to remove.
        """
        subscribers = self._subscribers.get(insight_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            del self._subscribers[insight_id]

    async def _publish(self, insight: InsightRead) -> None:
        """Push an update to every subscriber of its insight.

        Args:
            insight: The status snapshot to broadcast.
        """
        subscribers = self._subscribers.get(insight.id)
        if not subscribers:
            return
        for queue in list(subscribers):
            await queue.put(insight)

    async def _claim(self) -> _ClaimedJob | None:
        """Claim the next pending job and snapshot what processing needs.

        Returns:
            A :class:`_ClaimedJob`, or ``None`` when nothing is pending.
        """
        async with SessionFactory() as session:
            insight = await repo.claim_next_pending(session)
            if insight is None:
                return None
            article = await session.get(Article, insight.article_id)
            if article is None:  # pragma: no cover - FK guarantees presence
                return None
            return _ClaimedJob(
                insight_id=insight.id,
                article=ArticleBase.model_validate(article),
                running=InsightRead.model_validate(insight),
            )

    async def _run_loop(self) -> None:
        """Continuously claim and dispatch jobs until cancelled."""
        while True:
            job = await self._claim()
            if job is None:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=_IDLE_POLL_SECONDS)
                continue

            await self._publish(job.running)
            await self._semaphore.acquire()
            task = asyncio.create_task(self._process(job), name=f"insight-{job.insight_id}")
            self._children.add(task)
            task.add_done_callback(self._children.discard)

    async def _process(self, job: _ClaimedJob) -> None:
        """Run analysis for one claimed job and finalize + broadcast the result.

        Args:
            job: The claimed job to process.
        """
        started = time.perf_counter()
        try:
            try:
                result = await analyze_article(job.article, self._settings)
                timing_ms = int((time.perf_counter() - started) * 1000)
                async with SessionFactory() as session:
                    insight = await repo.finalize_success(
                        session, job.insight_id, result, self._settings.openai_model, timing_ms
                    )
                logger.info("insight %d done in %d ms", job.insight_id, timing_ms)
            except Exception as exc:  # pylint: disable=broad-exception-caught  # any failure must still mark the job FAILED
                async with SessionFactory() as session:
                    insight = await repo.finalize_failure(session, job.insight_id, str(exc))
                logger.warning("insight %d failed: %s", job.insight_id, exc)
            await self._publish(InsightRead.model_validate(insight))
        finally:
            self._semaphore.release()
