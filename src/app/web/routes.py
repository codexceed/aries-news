"""Server-rendered page routes: landing, search results, AI Insights, analyze.

These render HTML (Jinja2 + HTMX) and form the user-facing surface. They reuse
the same services as the JSON API: :class:`NewsService` for search and
:data:`insights_service` for analysis. The analyze action returns an HTML
fragment that connects to a per-insight SSE stream, so a card updates itself
when its (slow) AI job finishes while the user keeps browsing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.db import SessionFactory, get_session
from app.core.enums import JobStatus
from app.core.url import normalize_url
from app.repositories import insights as repo
from app.schemas import ArticleBase, InsightRead
from app.services.insights import insights_service
from app.services.news import NewsServiceError, get_news_service
from app.web.templating import templates

router = APIRouter(tags=["pages"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

SUGGESTIONS = ["AI regulation", "markets", "space", "climate", "elections"]
_SEARCH_LIMIT = 12
_TERMINAL = (JobStatus.DONE, JobStatus.FAILED)


def _normalize_view(view: str) -> str:
    """Return a safe view mode, defaulting unknown values to ``"cards"``."""
    return "list" if view == "list" else "cards"


def _sort_articles(articles: list[ArticleBase], sort: str) -> list[ArticleBase]:
    """Sort search results by the requested order.

    Args:
        articles: The fetched articles.
        sort: ``"newest"``, ``"oldest"``, or anything else for provider order.

    Returns:
        The (possibly) reordered list. Provider relevance order is preserved for
        unknown sort keys.
    """
    if sort not in {"newest", "oldest"}:
        return articles
    epoch = datetime.fromtimestamp(0, tz=None)

    def key(article: ArticleBase) -> datetime:
        published = article.published_at
        if published is None:
            return epoch
        return published.replace(tzinfo=None)

    return sorted(articles, key=key, reverse=sort == "newest")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the landing page (v1: a search bar and quick suggestions)."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {"active": "search", "suggestions": SUGGESTIONS, "query": ""},
    )


async def _existing_insights(
    session: AsyncSession, articles: list[ArticleBase]
) -> dict[str, InsightRead]:
    """Map article URL -> its stored insight, for the given articles.

    Looks up any analyses already persisted for these articles (keyed by
    normalized URL) so re-rendered results keep their summaries. The returned
    dict is keyed by the article's original ``url`` for direct template lookup.

    Args:
        session: The active database session.
        articles: The fetched search results.

    Returns:
        A mapping from each article's ``url`` to its :class:`InsightRead`,
        omitting articles that have no stored insight.
    """
    if not articles:
        return {}
    by_normalized = {normalize_url(a.url): a.url for a in articles}
    rows = await repo.list_by_normalized_urls(session, list(by_normalized))
    mapping: dict[str, InsightRead] = {}
    for row in rows:
        original = by_normalized.get(row.article.url_normalized)
        if original is not None:
            mapping[original] = InsightRead.model_validate(row)
    return mapping


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    session: SessionDep,
    q: str = "",
    view: str = "cards",
    sort: str = "relevance",
) -> HTMLResponse:
    """Render search results, or just the results region for HTMX requests.

    Args:
        request: The incoming request (used to detect HTMX).
        session: The request-scoped database session.
        q: The free-text query.
        view: ``"cards"`` or ``"list"``.
        sort: ``"relevance"`` (default), ``"newest"``, or ``"oldest"``.

    Returns:
        The full search page, or the ``#results-region`` fragment when the
        request comes from HTMX (view/sort changes).
    """
    query = q.strip()
    view = _normalize_view(view)
    articles: list[ArticleBase] = []
    error: str | None = None

    if query:
        try:
            articles = await get_news_service().search(query, max_results=_SEARCH_LIMIT)
            articles = _sort_articles(articles, sort)
        except NewsServiceError:
            error = "We couldn't reach the news service. Please try again in a moment."

    context = {
        "active": "search",
        "suggestions": SUGGESTIONS,
        "query": query,
        "articles": articles,
        "insights": await _existing_insights(session, articles),
        "view": view,
        "sort": sort,
        "error": error,
    }
    template = "partials/results_region.html" if "HX-Request" in request.headers else "search.html"
    return templates.TemplateResponse(request, template, context)


class AnalyzeForm(BaseModel):
    """Form payload for the analyze action (an article plus the active view)."""

    url: str
    title: str = ""
    source: str = ""
    description: str = ""
    image_url: str = ""
    published_at: str = ""
    view: str = "cards"


@router.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    session: SessionDep,
    form: Annotated[AnalyzeForm, Form()],
) -> HTMLResponse:
    """Request analysis for an article and return its updated card fragment.

    The returned fragment renders the "analyzing" state and connects to the
    article's SSE stream; an already-analyzed article returns its finished card
    immediately (idempotent).

    Args:
        request: The incoming request.
        session: The request-scoped database session.
        form: The submitted article fields and active view.

    Returns:
        The rendered article fragment.
    """
    published: datetime | None = None
    if form.published_at:
        try:
            published = datetime.fromisoformat(form.published_at)
        except ValueError:
            published = None

    article = ArticleBase(
        url=form.url,
        title=form.title,
        source=form.source,
        description=form.description or None,
        image_url=form.image_url or None,
        published_at=published,
    )
    insight = await insights_service.request_analysis(session, article)
    return templates.TemplateResponse(
        request,
        "partials/article.html",
        {
            "a": article,
            "ins": InsightRead.model_validate(insight),
            "view": _normalize_view(form.view),
        },
    )


@router.get("/insight/{insight_id}/stream")
async def insight_stream(insight_id: int, view: str = "cards") -> EventSourceResponse:
    """Stream the finished article card for an insight via Server-Sent Events.

    Subscribes to the insight's updates and emits a single ``message`` event —
    the fully rendered article fragment — once the job reaches a terminal state,
    then closes. The browser swaps it in, ending the connection.

    Args:
        insight_id: The insight to stream.
        view: ``"cards"`` or ``"list"`` so the rendered fragment matches.

    Returns:
        An SSE response carrying the terminal article fragment as HTML.
    """
    safe_view = _normalize_view(view)

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        async for update in insights_service.subscribe(insight_id):
            if update.status not in _TERMINAL:
                continue
            async with SessionFactory() as session:
                insight = await repo.get_with_article(session, insight_id)
            if insight is None:
                return
            article = ArticleBase.model_validate(insight.article)
            html = templates.get_template("partials/article.html").render(
                a=article,
                ins=InsightRead.model_validate(insight),
                view=safe_view,
            )
            yield {"event": "message", "data": html}
            return

    return EventSourceResponse(event_stream())


@router.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request, session: SessionDep) -> HTMLResponse:
    """Render the AI Insights page: every stored analysis, newest first."""
    rows = await repo.list_all_with_articles(session)
    items = [
        {
            "a": ArticleBase.model_validate(row.article),
            "ins": InsightRead.model_validate(row),
        }
        for row in rows
    ]
    return templates.TemplateResponse(
        request,
        "insights.html",
        {"active": "insights", "items": items},
    )
