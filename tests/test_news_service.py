"""Tests for the gnews-backed :class:`NewsService`."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.core.config import Settings
from app.services.news import NewsService, NewsServiceError

_GNEWS_PAYLOAD = {
    "totalArticles": 1,
    "articles": [
        {
            "title": "Markets rally",
            "description": "Stocks climbed today.",
            "content": "Full content here.",
            "url": "https://example.com/markets",
            "image": "https://example.com/markets.jpg",
            "publishedAt": "2026-06-30T12:00:00Z",
            "source": {"name": "Example News", "url": "https://example.com"},
        }
    ],
}


def _make_service(client: httpx.AsyncClient) -> NewsService:
    settings = Settings(
        gnews_api_key="test-key",
        gnews_base_url="https://gnews.test/api/v4",
        news_cache_ttl_seconds=300,
    )
    return NewsService(client=client, settings=settings)


async def test_search_maps_payload_to_article_base(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=_GNEWS_PAYLOAD)
    async with httpx.AsyncClient() as client:
        service = _make_service(client)
        articles = await service.search("markets")

    assert len(articles) == 1
    article = articles[0]
    assert article.url == "https://example.com/markets"
    assert article.title == "Markets rally"
    assert article.source == "Example News"
    assert article.description == "Stocks climbed today."
    assert article.image_url == "https://example.com/markets.jpg"
    assert article.published_at == datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


async def test_search_drops_articles_without_usable_url(httpx_mock: HTTPXMock) -> None:
    payload = {
        "totalArticles": 3,
        "articles": [
            {"title": "Good", "url": "https://example.com/ok", "source": {"name": "Wire"}},
            {"title": "Missing url", "source": {"name": "Wire"}},
            {"title": "Blank url", "url": "   ", "source": {"name": "Wire"}},
        ],
    }
    httpx_mock.add_response(json=payload)
    async with httpx.AsyncClient() as client:
        service = _make_service(client)
        articles = await service.search("markets")

    assert [a.url for a in articles] == ["https://example.com/ok"]


async def test_identical_search_is_served_from_cache(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=_GNEWS_PAYLOAD)
    async with httpx.AsyncClient() as client:
        service = _make_service(client)
        first = await service.search("Markets", max_results=10)
        second = await service.search("  markets ", max_results=10)

    assert first == second
    assert len(httpx_mock.get_requests()) == 1


async def test_request_uses_expected_params(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=_GNEWS_PAYLOAD)
    async with httpx.AsyncClient() as client:
        service = _make_service(client)
        await service.search("ai", max_results=5)

    request = httpx_mock.get_requests()[0]
    assert request.url.params["q"] == "ai"
    assert request.url.params["max"] == "5"
    assert request.url.params["lang"] == "en"
    assert request.url.params["apikey"] == "test-key"


async def test_request_query_is_normalized(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=_GNEWS_PAYLOAD)
    async with httpx.AsyncClient() as client:
        service = _make_service(client)
        await service.search("  spaced out  ")

    # The provider request uses the stripped query, not the raw input.
    assert httpx_mock.get_requests()[0].url.params["q"] == "spaced out"


async def test_server_error_raises_news_service_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=500, is_reusable=True)
    async with httpx.AsyncClient() as client:
        service = _make_service(client)
        with pytest.raises(NewsServiceError):
            await service.search("boom")


async def test_timeout_raises_news_service_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("timed out"), is_reusable=True)
    async with httpx.AsyncClient() as client:
        service = _make_service(client)
        with pytest.raises(NewsServiceError):
            await service.search("slow")


async def test_aclose_leaves_injected_client_open() -> None:
    async with httpx.AsyncClient() as client:
        service = NewsService(client=client, settings=Settings(gnews_api_key="test-key"))
        await service.aclose()
        # An injected client is owned by the caller and must stay open.
        assert not client.is_closed


async def test_aclose_owned_client_is_idempotent() -> None:
    service = NewsService(settings=Settings(gnews_api_key="test-key"))
    await service.aclose()
    # A second close on the owned client must not raise.
    await service.aclose()
