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
from app.api.insights import start_workers, stop_workers
from app.api.news import router as news_router
from app.services.news import close_news_service
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
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Start the background worker on boot and clean up on shutdown.

    Yields:
        Control to the running application.
    """
    await start_workers()
    try:
        yield
    finally:
        await stop_workers()
        await close_news_service()


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
