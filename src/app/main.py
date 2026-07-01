"""Application entrypoint.

Builds the FastAPI app: mounts static assets, includes the JSON API routers
(news, insights) and the server-rendered page routes, and runs a lifespan that
starts/stops the background insight worker and disposes the shared news client.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.insights import router as insights_router
from app.api.news import router as news_router
from app.services.insights import InsightsService
from app.services.jobs import JobQueue
from app.services.news import NewsService
from app.web.routes import router as web_router

_STATIC_DIR = Path(__file__).resolve().parent / "static"

meta_router = APIRouter()


@meta_router.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe used by local checks and the deploy platform.

    Returns:
        A small status payload.
    """
    return {"status": "ok"}


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    """Create the shared services, start the worker, and clean up on shutdown.

    The :class:`~app.services.news.NewsService`, the ``JobQueue``, and the
    :class:`~app.services.insights.InsightsService` (wrapping that same queue)
    are stored on ``app.state`` so every request reuses one process-wide
    instance (resolved via the getters in :mod:`app.dependencies`). The queue's
    worker is started here and stopped on shutdown, keeping the worker and the
    service's SSE subscriber registry on the identical queue object.

    Args:
        application: The application whose ``state`` holds the shared services.

    Yields:
        Control to the running application.
    """
    queue = JobQueue()
    application.state.job_queue = queue
    application.state.news_service = NewsService()
    application.state.insights_service = InsightsService(queue=queue)
    await queue.start()
    try:
        yield
    finally:
        await queue.stop()
        await application.state.news_service.aclose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        The configured application instance.
    """
    application = FastAPI(title="Aries News", version="0.1.0", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    application.include_router(meta_router)
    application.include_router(news_router)
    application.include_router(insights_router)
    application.include_router(web_router)
    return application


app = create_app()
