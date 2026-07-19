"""
app/main.py

Standalone FastAPI application entrypoint — used for running and
testing THIS MODULE in isolation (local dev, CI, Swagger exploration)
before it's mounted into the team's main monorepo app via
app/twitter_module.py.

In the final production monorepo, the team's top-level app/main.py
(owned by whoever integrates all modules — LinkedIn, Meta, AI Writer,
Scheduler, this Twitter module) will import `twitter_router` and
`register_twitter_error_handlers` from app/twitter_module.py instead of
running this file directly. This file remains useful standalone for:
  - `uvicorn app.main:app --reload` while developing this module alone
  - Integration tests that spin up just this module's routes
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.twitter_module import register_twitter_error_handlers, twitter_router
from app.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """
    Modern replacement for the deprecated @app.on_event("startup"/"shutdown")
    decorators. Code before `yield` runs on startup; code after runs on
    graceful shutdown.
    """
    logger.info("X (Twitter) Integration module starting up")
    yield
    logger.info("X (Twitter) Integration module shutting down")


app = FastAPI(
    title="X (Twitter) Integration Module",
    description=(
        "Standalone service exposing OAuth connection, posting, threads, "
        "media upload, and analytics for X (Twitter), built as an "
        "independently-owned module of a larger Social Media Management Tool."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

register_twitter_error_handlers(app)
app.include_router(twitter_router)


@app.get("/health", tags=["Health"], summary="Health check")
async def health_check() -> dict[str, str]:
    """Used by CI/CD and container orchestration to verify the service is up."""
    return {"status": "ok", "module": "twitter-integration"}
