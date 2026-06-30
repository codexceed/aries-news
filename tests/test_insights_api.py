"""Tests for the insights HTTP API (require a running PostgreSQL).

The background worker is not started here, so insights stay ``PENDING``; we test
the request/read endpoints and lightly smoke-test the SSE stream's initial event.
"""

from __future__ import annotations

import anyio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Sentiment
from app.repositories import insights as repo
from app.schemas import AnalysisResult

ARTICLE_PAYLOAD = {
    "url": "https://example.com/api-story",
    "title": "API headline",
    "source": "Example Wire",
    "description": "Body text.",
}


async def test_post_creates_pending_insight(client: AsyncClient) -> None:
    response = await client.post("/api/insights/", json=ARTICLE_PAYLOAD)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["summary"] is None


async def test_post_is_idempotent(client: AsyncClient) -> None:
    first = await client.post("/api/insights/", json=ARTICLE_PAYLOAD)
    second = await client.post("/api/insights/", json=ARTICLE_PAYLOAD)

    assert first.json()["id"] == second.json()["id"]


async def test_list_and_get_detail(client: AsyncClient) -> None:
    created = (await client.post("/api/insights/", json=ARTICLE_PAYLOAD)).json()

    listed = await client.get("/api/insights/")
    assert listed.status_code == 200
    assert any(item["id"] == created["id"] for item in listed.json())

    detail = await client.get(f"/api/insights/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == created["id"]


async def test_get_missing_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/insights/999999")
    assert response.status_code == 404


async def test_stream_emits_terminal_event(
    client: AsyncClient, async_session: AsyncSession
) -> None:
    # The httpx ASGI transport buffers the whole response, so the stream must
    # terminate: finalize the insight to DONE so the SSE endpoint emits one event
    # and closes (this also exercises the real terminal path).
    created = (await client.post("/api/insights/", json=ARTICLE_PAYLOAD)).json()
    await repo.finalize_success(
        async_session,
        created["id"],
        AnalysisResult(summary="Done.", sentiment=Sentiment.POSITIVE, score=0.5),
        model="test-model",
        timing_ms=12,
    )

    data_line: str | None = None
    with anyio.move_on_after(5):
        async with client.stream("GET", f"/api/insights/{created['id']}/stream") as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data_line = line
                    break

    assert data_line is not None
    assert str(created["id"]) in data_line
    assert "done" in data_line
