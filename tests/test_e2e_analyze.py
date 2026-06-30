"""E2E browser test for the core loop: search → analyze → loading → result.

Runs the real app **in-process** (uvicorn on a background thread) so the news
provider and OpenAI can be stubbed via monkeypatch — no external calls. Drives a
headless browser and asserts the card shows the loading state and then the
streamed (SSE) result.

Marked ``e2e``; run via ``make test-e2e`` (which runs e2e in isolation, so the
shared async engine has no connections left over from other tests).
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Coroutine, Iterator
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from app.core.enums import Sentiment
from app.schemas import AnalysisResult, ArticleBase

pytestmark = pytest.mark.e2e

_HOST = "127.0.0.1"
_TITLE = "Breakthrough in clean-energy storage"
_SUMMARY = "A concise stubbed summary produced for the analyze e2e test."
_ARTICLES = [
    ArticleBase(
        url="https://example.com/e2e-analyze",
        title=_TITLE,
        source="Stub Wire",
        description="Body text for the stubbed article.",
    )
]


def _free_port() -> int:
    """Return an unused TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


def _run_async(coro: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine on a fresh loop in a worker thread."""
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


async def _reset_schema() -> None:
    """Create a clean schema, dropping any connections bound to other loops."""
    from app.core.db import Base, engine

    await engine.dispose(close=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose(close=False)


async def _stub_analyze(article: ArticleBase, settings: Any = None) -> AnalysisResult:
    """Stand in for the OpenAI call; slow enough to show the loading state."""
    await asyncio.sleep(0.5)
    return AnalysisResult(summary=_SUMMARY, sentiment=Sentiment.POSITIVE, score=0.6)


async def _stub_search(self: Any, query: str, max_results: int = 10) -> list[ArticleBase]:
    """Stand in for the gnews search; returns one canned article."""
    return list(_ARTICLES)


@pytest.fixture(scope="module")
def analyze_server() -> Iterator[str]:
    """Reset the DB, stub upstreams, and run the app in a background thread."""
    import app.services.jobs as jobs_mod
    import app.services.news as news_mod

    _run_async(_reset_schema())

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(jobs_mod, "analyze_article", _stub_analyze)
    monkeypatch.setattr(news_mod.NewsService, "search", _stub_search)

    from app.main import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host=_HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.2)
        if not server.started:
            raise RuntimeError("server did not start in time")
        yield f"http://{_HOST}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        monkeypatch.undo()


def test_analyze_flow_shows_loading_then_result(analyze_server: str, page: Page) -> None:
    """Clicking analyze shows the loading state, then the SSE-streamed result."""
    page.goto(f"{analyze_server}/search?q=energy")

    card = page.locator("article.card", has_text=_TITLE)
    expect(card).to_be_visible()

    card.get_by_role("button", name="Summarize & analyze sentiment").click()

    # Loading state while the (stubbed, slow) analysis runs.
    expect(card.get_by_text("Analyzing")).to_be_visible()

    # The SSE stream swaps the finished result into the same card.
    expect(card.get_by_text(_SUMMARY)).to_be_visible(timeout=20_000)
    expect(card.get_by_text("Positive")).to_be_visible()
