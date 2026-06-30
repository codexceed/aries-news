"""baseline: articles and insights

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-30

Hand-authored baseline. Verify against autogenerate once a database is
available: ``make db-up && uv run alembic revision --autogenerate -m check``
should produce an empty diff.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

job_status = sa.Enum("pending", "running", "done", "failed", name="job_status")
sentiment = sa.Enum("positive", "neutral", "negative", name="sentiment")


def upgrade() -> None:
    """Create the ``articles`` and ``insights`` tables."""
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_normalized", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_articles")),
    )
    op.create_index(
        op.f("ix_articles_url_normalized"),
        "articles",
        ["url_normalized"],
        unique=True,
    )

    op.create_table(
        "insights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sentiment", sentiment, nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timing_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_insights_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_insights")),
    )
    op.create_index(op.f("ix_insights_article_id"), "insights", ["article_id"], unique=True)
    op.create_index(op.f("ix_insights_status"), "insights", ["status"], unique=False)


def downgrade() -> None:
    """Drop the ``insights`` and ``articles`` tables and their enum types."""
    op.drop_index(op.f("ix_insights_status"), table_name="insights")
    op.drop_index(op.f("ix_insights_article_id"), table_name="insights")
    op.drop_table("insights")
    op.drop_index(op.f("ix_articles_url_normalized"), table_name="articles")
    op.drop_table("articles")
    sentiment.drop(op.get_bind(), checkfirst=True)
    job_status.drop(op.get_bind(), checkfirst=True)
