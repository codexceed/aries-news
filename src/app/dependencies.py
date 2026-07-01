"""Shared FastAPI dependencies resolving app-scoped services from ``app.state``.

The :class:`~app.services.news.NewsService` and
:class:`~app.services.insights.InsightsService` are created once during the
application lifespan (see :mod:`app.main`) and stored on ``app.state``. These
getters expose them to path operations via ``Depends`` so every request — JSON
API or server-rendered page — reuses the same process-wide instance. Tests
swap a service by overriding the getter through ``app.dependency_overrides``.
"""

from __future__ import annotations

from fastapi import Request

from app.services.insights import InsightsService
from app.services.news import NewsService


def get_news_service(request: Request) -> NewsService:
    """Return the process-wide news service stored on the application state.

    Args:
        request: The incoming request, used to reach ``request.app.state``.

    Returns:
        The shared :class:`~app.services.news.NewsService` created at startup.

    Raises:
        RuntimeError: If ``app.state.news_service`` was never populated (the
            lifespan did not run, e.g. a bare test app missing the wiring).
    """
    try:
        service: NewsService = request.app.state.news_service
    except AttributeError as exc:
        raise RuntimeError(
            "news_service is not on app.state; is the application lifespan running?"
        ) from exc
    return service


def get_insights_service(request: Request) -> InsightsService:
    """Return the process-wide insights service stored on the application state.

    Args:
        request: The incoming request, used to reach ``request.app.state``.

    Returns:
        The shared :class:`~app.services.insights.InsightsService` created at
        startup.

    Raises:
        RuntimeError: If ``app.state.insights_service`` was never populated (the
            lifespan did not run, e.g. a bare test app missing the wiring).
    """
    try:
        service: InsightsService = request.app.state.insights_service
    except AttributeError as exc:
        raise RuntimeError(
            "insights_service is not on app.state; is the application lifespan running?"
        ) from exc
    return service
