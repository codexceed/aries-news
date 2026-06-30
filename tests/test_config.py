"""Tests for settings, focused on the database-URL driver coercion."""

from __future__ import annotations

import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Platform-style URLs are coerced to the async driver.
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        # Already async — left untouched.
        ("postgresql+asyncpg://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
    ],
)
def test_database_url_uses_async_driver(given: str, expected: str) -> None:
    """Any Postgres URL ends up on the asyncpg driver exactly once."""
    settings = Settings(database_url=given)
    assert settings.database_url == expected
