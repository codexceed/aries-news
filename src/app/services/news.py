"""Async news client over the gnews.io API with retries and a TTL cache.

The :class:`NewsService` fetches articles from gnews.io, maps them onto the
shared :class:`~app.schemas.article.ArticleBase` schema, retries transient
failures, and caches identical queries in memory to protect the free-tier
quota (100 requests/day).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings, get_settings
from app.schemas.article import ArticleBase

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0
_RETRY_ATTEMPTS = 3


class NewsServiceError(RuntimeError):
    """Raised when the news provider cannot be reached or returns bad data."""


def _is_transient(exc: BaseException) -> bool:
    """Return whether an exception is worth retrying.

    Transient failures are transport-level errors (timeouts, connection
    resets) and server-side ``5xx`` responses.

    Args:
        exc: The exception raised during a request attempt.

    Returns:
        ``True`` if the request should be retried, ``False`` otherwise.
    """
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class NewsService:
    """Async client for the gnews.io search endpoint.

    The service owns an :class:`httpx.AsyncClient` unless one is injected, in
    which case the caller is responsible for its lifecycle. Results for
    identical ``(query, max_results)`` pairs are cached in memory for
    ``news_cache_ttl_seconds`` so that repeated lookups do not consume the
    free-tier request quota.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialise the service.

        Args:
            client: An optional pre-built async HTTP client. When provided the
                caller owns it and :meth:`aclose` will not close it. When
                omitted the service creates and owns one.
            settings: Optional settings override. Defaults to
                :func:`~app.core.config.get_settings`.
        """
        self._settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)
        self._cache: dict[tuple[str, int], tuple[float, list[ArticleBase]]] = {}

    async def search(self, query: str, max_results: int = 10) -> list[ArticleBase]:
        """Search gnews.io for articles matching ``query``.

        Identical queries are served from the in-memory cache for the
        configured TTL without issuing a second HTTP request. Articles
        without a usable ``url`` (empty or whitespace) are dropped, since a
        blank url is a poor idempotency key and a dead "read original" link.

        Args:
            query: The free-text search query.
            max_results: The maximum number of articles to request.

        Returns:
            The matching articles as :class:`ArticleBase` instances.

        Raises:
            NewsServiceError: If the provider is unreachable or returns a
                response that cannot be parsed.
        """
        cache_key = (query.strip().lower(), max_results)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("news cache hit for %r", cache_key)
            return cached

        payload = await self._request(query, max_results)
        raw_articles = payload.get("articles", [])
        articles = [
            article for raw in raw_articles if (article := self._to_article(raw)).url.strip()
        ]
        dropped = len(raw_articles) - len(articles)
        if dropped:
            logger.info("dropped %d article(s) with no usable url for query %r", dropped, query)
        self._cache[cache_key] = (time.monotonic(), articles)
        logger.info("fetched %d articles for query %r", len(articles), query)
        return articles

    def _cache_get(self, key: tuple[str, int]) -> list[ArticleBase] | None:
        """Return a cached result for ``key`` if it has not expired.

        Args:
            key: The normalised cache key.

        Returns:
            The cached articles, or ``None`` on a miss or expiry.
        """
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, articles = entry
        if time.monotonic() - stored_at >= self._settings.news_cache_ttl_seconds:
            del self._cache[key]
            return None
        return articles

    async def _request(self, query: str, max_results: int) -> dict[str, Any]:
        """Issue the gnews.io request, retrying transient failures.

        Args:
            query: The free-text search query.
            max_results: The maximum number of articles to request.

        Returns:
            The decoded JSON payload.

        Raises:
            NewsServiceError: If the request ultimately fails or the response
                is not valid JSON.
        """
        url = f"{self._settings.gnews_base_url}/search"
        params: dict[str, str | int] = {
            "q": query,
            "max": max_results,
            "lang": "en",
            "apikey": self._settings.gnews_api_key,
        }

        retrying = retry(
            stop=stop_after_attempt(_RETRY_ATTEMPTS),
            wait=wait_exponential(multiplier=0.5, max=8),
            retry=retry_if_exception(_is_transient),
            reraise=True,
        )

        async def _do_request() -> dict[str, Any]:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

        try:
            return await retrying(_do_request)()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("news request failed for query %r: %s", query, exc)
            raise NewsServiceError(f"news provider request failed: {exc}") from exc

    @staticmethod
    def _to_article(raw: dict[str, Any]) -> ArticleBase:
        """Map a raw gnews article object onto :class:`ArticleBase`.

        Args:
            raw: A single article object from the gnews response.

        Returns:
            The mapped :class:`ArticleBase`.
        """
        source: dict[str, Any] = raw.get("source") or {}
        return ArticleBase(
            url=raw.get("url", ""),
            title=raw.get("title", ""),
            source=source.get("name", ""),
            description=raw.get("description"),
            image_url=raw.get("image"),
            published_at=raw.get("publishedAt"),
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this service owns it."""
        if self._owns_client:
            await self._client.aclose()


class _ServiceHolder:
    """Holds the lazily created process-wide :class:`NewsService`."""

    instance: NewsService | None = None


def get_news_service() -> NewsService:
    """Return the process-wide :class:`NewsService` singleton.

    Returns:
        The lazily created shared service instance.
    """
    if _ServiceHolder.instance is None:
        _ServiceHolder.instance = NewsService()
    return _ServiceHolder.instance


async def close_news_service() -> None:
    """Close and discard the shared :class:`NewsService` singleton."""
    if _ServiceHolder.instance is not None:
        await _ServiceHolder.instance.aclose()
        _ServiceHolder.instance = None
