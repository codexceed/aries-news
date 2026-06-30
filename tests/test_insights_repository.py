"""Tests for the insights repository (require a running PostgreSQL).

Cover article/insight idempotency, the atomic claim transition, and stale-job
reaping -- the concurrency-critical behaviors the worker depends on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JobStatus, Sentiment
from app.models import Article, Insight
from app.repositories import insights as repo
from app.schemas import AnalysisResult, ArticleBase

ARTICLE = ArticleBase(
    url="https://example.com/story?utm_source=twitter",
    title="A headline",
    source="Example Wire",
    description="Some description.",
)


async def _count(session: AsyncSession, model: type[Article] | type[Insight]) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def test_upsert_article_is_idempotent(async_session: AsyncSession) -> None:
    first = await repo.upsert_article(async_session, ARTICLE)
    second = await repo.upsert_article(async_session, ARTICLE)

    assert first.id == second.id
    assert await _count(async_session, Article) == 1


async def test_get_or_create_pending_insight_is_idempotent(
    async_session: AsyncSession,
) -> None:
    first = await repo.get_or_create_pending_insight(async_session, ARTICLE)
    second = await repo.get_or_create_pending_insight(async_session, ARTICLE)

    assert first.id == second.id
    assert first.status == JobStatus.PENDING
    assert await _count(async_session, Insight) == 1


async def test_claim_next_pending_transitions_to_running(
    async_session: AsyncSession,
) -> None:
    created = await repo.get_or_create_pending_insight(async_session, ARTICLE)

    claimed = await repo.claim_next_pending(async_session)
    assert claimed is not None
    assert claimed.id == created.id
    assert claimed.status == JobStatus.RUNNING
    assert claimed.started_at is not None
    assert claimed.attempts == 1

    # Nothing left pending, so a second claim returns None.
    assert await repo.claim_next_pending(async_session) is None


async def test_finalize_success_records_result(async_session: AsyncSession) -> None:
    created = await repo.get_or_create_pending_insight(async_session, ARTICLE)
    await repo.claim_next_pending(async_session)

    result = AnalysisResult(summary="done", sentiment=Sentiment.NEGATIVE, score=-0.4)
    done = await repo.finalize_success(async_session, created.id, result, "gpt-4.1-nano", 123)

    assert done.status == JobStatus.DONE
    assert done.summary == "done"
    assert done.score == -0.4
    assert done.model == "gpt-4.1-nano"
    assert done.timing_ms == 123
    assert done.completed_at is not None


async def test_failed_insight_is_reset_on_retry(async_session: AsyncSession) -> None:
    created = await repo.get_or_create_pending_insight(async_session, ARTICLE)
    await repo.claim_next_pending(async_session)
    failed = await repo.finalize_failure(async_session, created.id, "boom")
    assert failed.status == JobStatus.FAILED
    assert failed.error == "boom"

    # "Try again" re-requests the same article → the failed row is reset to
    # PENDING (not returned as-is and not duplicated).
    retried = await repo.get_or_create_pending_insight(async_session, ARTICLE)
    assert retried.id == created.id
    assert retried.status == JobStatus.PENDING
    assert retried.error is None
    assert retried.completed_at is None
    assert await _count(async_session, Insight) == 1


async def test_reap_stale_resets_running_job(async_session: AsyncSession) -> None:
    created = await repo.get_or_create_pending_insight(async_session, ARTICLE)
    claimed = await repo.claim_next_pending(async_session)
    assert claimed is not None

    # Backdate the start so it falls outside the staleness window.
    stale = await async_session.get(Insight, created.id)
    assert stale is not None
    stale.started_at = datetime.now(UTC) - timedelta(hours=1)
    await async_session.commit()

    reaped = await repo.reap_stale(async_session, stale_after_seconds=120)
    assert reaped == 1

    refreshed = await async_session.get(Insight, created.id)
    assert refreshed is not None
    assert refreshed.status == JobStatus.PENDING
    assert refreshed.started_at is None
