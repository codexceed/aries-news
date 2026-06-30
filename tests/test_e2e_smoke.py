"""End-to-end browser smoke test (Playwright).

Boots the real app against the configured PostgreSQL, seeds one finished
insight, and drives a headless browser to confirm the rendered UI works: the
landing search box, and the AI Insights page with its sentiment-tinted card,
spectrum marker, and Alpine sentiment filter. No external APIs are called.

Marked ``e2e`` (excluded from the fast suite); run via ``make test-e2e``.
Requires ``playwright install chromium``.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import threading
import time
from collections.abc import Coroutine, Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

_HOST = "127.0.0.1"
_SEEDED_SUMMARY = "A calm summary for the smoke test."


async def _seed() -> None:
    """Reset the schema and seed a single DONE (positive) insight."""
    from app.core.db import Base, SessionFactory, engine
    from app.core.enums import Sentiment
    from app.repositories import insights as repo
    from app.schemas import AnalysisResult, ArticleBase

    await engine.dispose(close=False)  # drop connections bound to other loops
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionFactory() as session:
        insight = await repo.get_or_create_pending_insight(
            session,
            ArticleBase(
                url="https://example.com/e2e-smoke",
                title="Coalition agrees on a calm, hopeful plan",
                source="Smoke Wire",
                description="Seeded for the browser smoke test.",
            ),
        )
        await repo.finalize_success(
            session,
            insight.id,
            AnalysisResult(summary=_SEEDED_SUMMARY, sentiment=Sentiment.POSITIVE, score=0.6),
            model="test-model",
            timing_ms=10,
        )
    await engine.dispose()


def _run_async(coro: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine on a fresh loop in a worker thread.

    pytest-asyncio already owns the session event loop, so ``asyncio.run`` here
    would fail; a dedicated thread gives the seeding its own loop.
    """
    error: list[BaseException] = []

    def target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        except BaseException as exc:
            error.append(exc)
        finally:
            loop.close()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if error:
        raise error[0]


def _free_port() -> int:
    """Return an unused TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_server() -> Iterator[str]:
    """Seed the DB, run uvicorn in a subprocess, and yield its base URL."""
    _run_async(_seed())
    port = _free_port()
    base_url = f"http://{_HOST}:{port}"
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--host", _HOST, "--port", str(port)],
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise RuntimeError("server did not become healthy in time")
        yield base_url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_landing_has_search(live_server: str, page: Page) -> None:
    """The landing page shows the hero and a usable search box."""
    page.goto(live_server)
    expect(page.locator("input.search__input")).to_be_visible()
    expect(page.locator("h1")).to_contain_text("Read the day")


def test_insights_card_renders_and_filters(live_server: str, page: Page) -> None:
    """The AI Insights page shows the analyzed card and the filter hides it."""
    page.goto(f"{live_server}/insights")

    card = page.locator("article.card.is-analyzed").first
    expect(card).to_be_visible()
    expect(card).to_contain_text(_SEEDED_SUMMARY)
    expect(card.locator(".spectrum__marker")).to_be_visible()

    # The seeded insight is positive; filtering to Negative should hide it.
    page.get_by_role("button", name="Negative").click()
    expect(card).to_be_hidden()
    page.get_by_role("button", name="All").click()
    expect(card).to_be_visible()
