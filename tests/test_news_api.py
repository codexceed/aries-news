"""Tests for the news API router."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.news import router, search_news
from app.schemas.article import ArticleBase
from app.services.news import NewsService, NewsServiceError, get_news_service

_CANNED = [
    ArticleBase(
        url="https://example.com/a",
        title="Canned headline",
        source="Fake Wire",
        description="A canned description.",
        image_url="https://example.com/a.jpg",
        published_at=None,
    )
]


class _FakeService:
    def __init__(self, error: bool = False) -> None:
        self.error = error

    async def search(self, query: str, max_results: int = 10) -> list[ArticleBase]:
        if self.error:
            raise NewsServiceError("upstream down")
        return _CANNED


def _build_app(service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_news_service] = lambda: service
    return app


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_search_returns_articles() -> None:
    app = _build_app(_FakeService())
    async with _client(app) as client:
        response = await client.get("/api/news/search", params={"q": "markets"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == "Canned headline"
    assert body[0]["source"] == "Fake Wire"


async def test_blank_query_returns_400() -> None:
    app = _build_app(_FakeService())
    async with _client(app) as client:
        response = await client.get("/api/news/search", params={"q": "   "})

    assert response.status_code == 400


async def test_upstream_failure_returns_502() -> None:
    app = _build_app(_FakeService(error=True))
    async with _client(app) as client:
        response = await client.get("/api/news/search", params={"q": "markets"})

    assert response.status_code == 502


async def test_max_out_of_range_returns_422() -> None:
    app = _build_app(_FakeService())
    async with _client(app) as client:
        response = await client.get("/api/news/search", params={"q": "markets", "max": 99})

    assert response.status_code == 422


def test_search_news_is_wired_to_news_service() -> None:
    # Sanity: the dependency default resolves to the real singleton type.
    assert isinstance(get_news_service(), NewsService)
    assert search_news.__name__ == "search_news"
