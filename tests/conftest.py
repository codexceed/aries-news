"""Shared pytest fixtures: a transactional test database and an ASGI client.

The suite creates and drops tables on every test, so it must never run against
the developer's dev database -- doing so would wipe the schema the running app
depends on. To guarantee isolation, this module redirects ``DATABASE_URL`` to a
dedicated ``<db>_test`` sibling database (created on demand) *before* importing
anything under ``app``, so the app's module-level engine and every fixture bind
to the test database. Each test then gets a clean schema: all tables are created
before it and dropped afterwards.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _redirect_to_test_database() -> None:
    """Point ``DATABASE_URL`` at a ``<db>_test`` sibling before any app import.

    Idempotent: a URL whose database already ends in ``_test`` is left as-is.
    """
    default = "postgresql+asyncpg://aries:aries@localhost:5432/aries"
    url = make_url(os.environ.get("DATABASE_URL", default))
    name = url.database or "aries"
    if not name.endswith("_test"):
        url = url.set(database=f"{name}_test")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)


_redirect_to_test_database()

# Imported after the redirect so `app.core.db`'s engine binds to the test DB.
from app.api.insights import router as insights_router  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import Base, get_session  # noqa: E402


async def _ensure_database_exists(database_url: str) -> None:
    """Create the target database if it does not already exist.

    Connects to the server's maintenance ``postgres`` database (in AUTOCOMMIT,
    since ``CREATE DATABASE`` cannot run inside a transaction) and creates the
    target when missing, so the test DB needs no manual setup.
    """
    url = make_url(database_url)
    admin_engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin_engine.dispose()


# Test modules that need a running PostgreSQL. Auto-marked `db` so the fast
# pre-commit subset (`-m "not e2e and not db"`) can skip them.
_DB_TEST_FILES = frozenset({"test_insights_repository.py", "test_jobs.py", "test_insights_api.py"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag DB-backed test modules with the ``db`` marker."""
    for item in items:
        if item.path.name in _DB_TEST_FILES:
            item.add_marker(pytest.mark.db)


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Yield an async engine with a freshly created schema, dropped on teardown.

    Also disposes the application's module-level engine, whose pooled
    connections cache prepared-statement plans (incl. enum type OIDs). Recreating
    the schema here changes those OIDs, so without this the SSE/worker code paths
    that use the shared engine could hit a stale plan.
    """
    from app.core.db import engine as app_engine

    settings = get_settings()
    await _ensure_database_exists(settings.database_url)
    engine = create_async_engine(settings.database_url)
    await app_engine.dispose(close=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
        await app_engine.dispose(close=False)


@pytest_asyncio.fixture
async def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the test engine."""
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def async_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a database session bound to the test engine."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """Yield an ASGI client for an app exposing the insights router."""
    app = FastAPI()
    app.include_router(insights_router)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
