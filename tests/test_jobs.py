"""Tests for the in-process JobQueue (require a running PostgreSQL).

``analyze_article`` is monkeypatched to a fast fake so the worker runs offline.
We verify a created job is processed to ``DONE`` and that a subscriber receives
the terminal update.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.enums import JobStatus, Sentiment
from app.repositories import insights as repo
from app.schemas import AnalysisResult, ArticleBase, InsightRead
from app.services import jobs as jobs_module
from app.services.jobs import JobQueue

ARTICLE = ArticleBase(
    url="https://example.com/job",
    title="Job headline",
    source="Example Wire",
    description="Body text.",
)

_FAKE_RESULT = AnalysisResult(summary="fake summary", sentiment=Sentiment.POSITIVE, score=0.5)


async def _fake_analyze(_article: ArticleBase, _settings: Settings | None = None) -> AnalysisResult:
    return _FAKE_RESULT


async def test_job_processed_to_done_and_broadcast(
    db_engine: object,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs_module, "analyze_article", _fake_analyze)

    async with session_factory() as session:
        created = await repo.get_or_create_pending_insight(session, ARTICLE)

    queue = JobQueue(
        settings=Settings(insights_max_concurrency=2, insights_stale_after_seconds=120)
    )
    subscriber = queue.subscribe_queue(created.id)
    await queue.start()
    queue.notify()

    try:
        terminal: InsightRead | None = None
        async with asyncio.timeout(10):
            while True:
                update = await subscriber.get()
                if update.status in (JobStatus.DONE, JobStatus.FAILED):
                    terminal = update
                    break
    finally:
        await queue.stop()

    assert terminal is not None
    assert terminal.status == JobStatus.DONE
    assert terminal.summary == "fake summary"

    async with session_factory() as session:
        stored = await repo.get(session, created.id)
    assert stored is not None
    assert stored.status == JobStatus.DONE
    assert stored.score == 0.5
