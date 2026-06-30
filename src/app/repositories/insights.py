"""Database access for articles and their AI insight jobs.

Every function takes an :class:`~sqlalchemy.ext.asyncio.AsyncSession` and is the
single place that knows how an insight row moves through its lifecycle:
``PENDING -> RUNNING -> DONE | FAILED``. The claim and reap helpers are the
concurrency-critical pieces -- they are what stop two workers from processing the
same job and what recovers jobs orphaned by a crash.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import JobStatus
from app.core.url import normalize_url
from app.models import Article, Insight
from app.schemas import AnalysisResult, ArticleBase


async def upsert_article(session: AsyncSession, article: ArticleBase) -> Article:
    """Insert ``article`` or return the existing row with the same normalized URL.

    The normalized URL is the idempotency key, so the same story reached through
    different tracking links collapses onto one row. The insert uses PostgreSQL
    ``ON CONFLICT (url_normalized) DO NOTHING`` so a concurrent insert of the same
    URL cannot raise; the row is then read back unconditionally.

    Args:
        session: The active database session.
        article: The article to persist.

    Returns:
        The persisted :class:`Article` (newly inserted or pre-existing).
    """
    normalized = normalize_url(article.url)
    stmt = (
        pg_insert(Article)
        .values(
            url=article.url,
            url_normalized=normalized,
            title=article.title,
            source=article.source,
            description=article.description,
            image_url=article.image_url,
            published_at=article.published_at,
        )
        .on_conflict_do_nothing(index_elements=["url_normalized"])
    )
    await session.execute(stmt)
    await session.flush()

    result = await session.execute(select(Article).where(Article.url_normalized == normalized))
    return result.scalar_one()


async def get_or_create_pending_insight(session: AsyncSession, article: ArticleBase) -> Insight:
    """Return the article's single insight, queuing or re-queuing as needed.

    Mostly idempotent: a ``PENDING``/``RUNNING``/``DONE`` insight is returned
    unchanged, so in-flight or finished analyses are never duplicated. A
    ``FAILED`` insight, however, is **reset to ``PENDING``** (its error and any
    stale result cleared) so the user's "Try again" actually retries. The insert
    relies on the unique ``article_id`` constraint plus ``ON CONFLICT DO NOTHING``
    to stay race-safe.

    Args:
        session: The active database session.
        article: The article to analyze.

    Returns:
        The existing, reset, or newly created :class:`Insight`.
    """
    persisted = await upsert_article(session, article)

    stmt = (
        pg_insert(Insight)
        .values(article_id=persisted.id, status=JobStatus.PENDING, attempts=0)
        .on_conflict_do_nothing(index_elements=["article_id"])
    )
    await session.execute(stmt)
    await session.flush()

    result = await session.execute(select(Insight).where(Insight.article_id == persisted.id))
    insight = result.scalar_one()

    if insight.status == JobStatus.FAILED:
        insight.status = JobStatus.PENDING
        insight.error = None
        insight.summary = None
        insight.sentiment = None
        insight.score = None
        insight.started_at = None
        insight.completed_at = None
        insight.timing_ms = None

    await session.commit()
    await session.refresh(insight)
    return insight


async def claim_next_pending(session: AsyncSession) -> Insight | None:
    """Atomically claim the oldest pending insight for processing.

    Selects with ``FOR UPDATE SKIP LOCKED`` so that concurrent workers each take a
    distinct row instead of blocking or double-processing. The claimed row is moved
    to ``RUNNING``, stamped with ``started_at``, and has its attempt counter
    incremented, all committed before returning.

    Args:
        session: The active database session.

    Returns:
        The claimed :class:`Insight`, or ``None`` when no job is pending.
    """
    stmt = (
        select(Insight)
        .where(Insight.status == JobStatus.PENDING)
        .order_by(Insight.created_at.asc(), Insight.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    insight = result.scalar_one_or_none()
    if insight is None:
        return None

    insight.status = JobStatus.RUNNING
    insight.started_at = datetime.now(UTC)
    insight.attempts += 1
    await session.commit()
    await session.refresh(insight)
    return insight


async def finalize_success(
    session: AsyncSession,
    insight_id: int,
    result: AnalysisResult,
    model: str,
    timing_ms: int,
) -> Insight:
    """Mark an insight ``DONE`` and persist the analysis result.

    Args:
        session: The active database session.
        insight_id: The insight to finalize.
        result: The structured analysis output to store.
        model: The model identifier that produced the result.
        timing_ms: Wall-clock duration of the analysis call in milliseconds.

    Returns:
        The updated :class:`Insight`.

    Raises:
        LookupError: If no insight with ``insight_id`` exists.
    """
    insight = await session.get(Insight, insight_id)
    if insight is None:
        raise LookupError(f"insight {insight_id} not found")

    insight.status = JobStatus.DONE
    insight.summary = result.summary
    insight.sentiment = result.sentiment
    insight.score = result.score
    insight.model = model
    insight.error = None
    insight.timing_ms = timing_ms
    insight.completed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(insight)
    return insight


async def finalize_failure(session: AsyncSession, insight_id: int, error: str) -> Insight:
    """Mark an insight ``FAILED`` and record the error message.

    Args:
        session: The active database session.
        insight_id: The insight to finalize.
        error: A human-readable description of the failure.

    Returns:
        The updated :class:`Insight`.

    Raises:
        LookupError: If no insight with ``insight_id`` exists.
    """
    insight = await session.get(Insight, insight_id)
    if insight is None:
        raise LookupError(f"insight {insight_id} not found")

    insight.status = JobStatus.FAILED
    insight.error = error
    insight.completed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(insight)
    return insight


async def reap_stale(session: AsyncSession, stale_after_seconds: int) -> int:
    """Reset ``RUNNING`` insights stuck past the staleness threshold to ``PENDING``.

    A worker that crashes mid-job leaves its row ``RUNNING`` forever; this recovers
    those orphans so another worker can pick them up. Called once on startup and
    safe to call periodically.

    Args:
        session: The active database session.
        stale_after_seconds: Maximum age of ``started_at`` before a running job is
            considered orphaned.

    Returns:
        The number of insights reset to ``PENDING``.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    stmt = (
        update(Insight)
        .where(Insight.status == JobStatus.RUNNING, Insight.started_at < cutoff)
        .values(status=JobStatus.PENDING, started_at=None)
        .returning(Insight.id)
    )
    result = await session.execute(stmt)
    reaped = list(result.scalars().all())
    await session.commit()
    return len(reaped)


async def get(session: AsyncSession, insight_id: int) -> Insight | None:
    """Return a single insight by id, or ``None`` if it does not exist.

    Args:
        session: The active database session.
        insight_id: The insight identifier.

    Returns:
        The :class:`Insight` or ``None``.
    """
    return await session.get(Insight, insight_id)


async def list_all(session: AsyncSession) -> list[Insight]:
    """Return all insights, newest first.

    Args:
        session: The active database session.

    Returns:
        Every :class:`Insight` ordered by creation time descending.
    """
    stmt = select(Insight).order_by(Insight.created_at.desc(), Insight.id.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_with_article(session: AsyncSession, insight_id: int) -> Insight | None:
    """Return an insight by id with its :class:`Article` eagerly loaded.

    Args:
        session: The active database session.
        insight_id: The insight identifier.

    Returns:
        The :class:`Insight` (with ``article`` populated) or ``None``.
    """
    stmt = select(Insight).options(selectinload(Insight.article)).where(Insight.id == insight_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_all_with_articles(session: AsyncSession) -> list[Insight]:
    """Return all insights (newest first) with their articles eagerly loaded.

    Used to render the AI Insights page, which shows each insight alongside its
    source article without triggering lazy loads.

    Args:
        session: The active database session.

    Returns:
        Every :class:`Insight` with ``article`` populated, newest first.
    """
    stmt = (
        select(Insight)
        .options(selectinload(Insight.article))
        .order_by(Insight.created_at.desc(), Insight.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
