"""The ``insights`` table: one AI analysis job + result per article."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import JobStatus, Sentiment

if TYPE_CHECKING:
    from app.models.article import Article


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Use the enum's (lowercase) values, not member names, for the PG type.

    Without this, SQLAlchemy builds the native enum from member names
    (``PENDING``), which disagrees with the StrEnum values, the migration, and
    the JSON API (``pending``).

    Args:
        enum_cls: The enumeration class backing the column.

    Returns:
        The enum member values as strings, in definition order.
    """
    return [str(member.value) for member in enum_cls]


class Insight(Base):
    """AI summary + sentiment for an article, and the job state that produced it.

    The row is created in :attr:`JobStatus.PENDING` when analysis is requested,
    claimed transactionally by a worker (``FOR UPDATE SKIP LOCKED``) into
    :attr:`JobStatus.RUNNING`, and finalized as ``DONE`` or ``FAILED``.
    """

    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), unique=True, index=True
    )

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=_enum_values),
        default=JobStatus.PENDING,
        server_default=JobStatus.PENDING.value,
        index=True,
    )
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    sentiment: Mapped[Sentiment | None] = mapped_column(
        Enum(Sentiment, name="sentiment", values_callable=_enum_values), default=None
    )
    # Continuous sentiment in [-1, 1]; drives the spectrum marker and halo color.
    score: Mapped[float | None] = mapped_column(Float, default=None)
    model: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    timing_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    article: Mapped[Article] = relationship(back_populates="insight")
