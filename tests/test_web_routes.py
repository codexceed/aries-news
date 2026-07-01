"""Tests for pure helpers in the web page routes (no DB, no network)."""

from __future__ import annotations

from datetime import datetime

from app.schemas import ArticleBase

# Unit-testing a module-private pure helper is intentional here.
from app.web.routes import _sort_articles  # pyright: ignore[reportPrivateUsage]


def _article(source: str, published_at: datetime | None = None) -> ArticleBase:
    return ArticleBase(
        url=f"https://example.com/{source}",
        title=f"{source} headline",
        source=source,
        published_at=published_at,
    )


def test_sort_by_source_is_case_insensitive_alphabetical() -> None:
    articles = [_article("Zeta"), _article("alpha"), _article("Beta")]

    ordered = [a.source for a in _sort_articles(articles, "source")]

    assert ordered == ["alpha", "Beta", "Zeta"]


def test_sort_newest_and_oldest_by_published_at() -> None:
    old = _article("Old Wire", datetime(2020, 1, 1))
    new = _article("New Wire", datetime(2024, 1, 1))
    articles = [old, new]

    assert [a.source for a in _sort_articles(articles, "newest")] == ["New Wire", "Old Wire"]
    assert [a.source for a in _sort_articles(articles, "oldest")] == ["Old Wire", "New Wire"]


def test_missing_published_at_sorts_as_oldest() -> None:
    dated = _article("Dated", datetime(2022, 6, 1))
    undated = _article("Undated", None)

    # Newest first: the dated article outranks the epoch-defaulted undated one.
    assert [a.source for a in _sort_articles([undated, dated], "newest")] == ["Dated", "Undated"]


def test_unknown_sort_key_preserves_provider_order() -> None:
    articles = [_article("First"), _article("Second")]

    assert _sort_articles(articles, "relevance") is articles
