"""
app/middleware/error_handler.py

Registers exception handlers that translate our custom domain
exceptions (app/exceptions/twitter_exceptions.py) into consistent JSON
error responses.

WHY THIS IS THE ONLY PLACE THAT KNOWS ABOUT HTTP STATUS CODES FOR OUR
DOMAIN ERRORS: services raise `TokenExpiredError`, not `HTTPException`.
This keeps services reusable outside of FastAPI request context (e.g.
called directly from a Celery task by the scheduler module). This file
is the single translation boundary between "what went wrong in our
domain" and "what HTTP response the client sees."
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions.twitter_exceptions import (
    TwitterBaseError,
    TwitterRateLimitError,
)
from app.utils.logger import get_logger, safe_log_context

logger = get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """Called once from app/main.py during app startup."""

    @app.exception_handler(TwitterRateLimitError)
    async def handle_rate_limit_error(request: Request, exc: TwitterRateLimitError) -> JSONResponse:
        logger.warning(
            "Rate limit error on %s %s: %s",
            request.method, request.url.path, exc.detail,
            extra=safe_log_context(exc.context),
        )
        headers = {}
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(exc.retry_after_seconds)

        return JSONResponse(
            status_code=exc.http_status_code,
            content={
                "error_code": exc.error_code,
                "detail": exc.detail,
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers=headers,
        )

    @app.exception_handler(TwitterBaseError)
    async def handle_twitter_base_error(request: Request, exc: TwitterBaseError) -> JSONResponse:
        log_fn = logger.error if exc.http_status_code >= 500 else logger.warning
        log_fn(
            "%s on %s %s: %s",
            exc.error_code, request.method, request.url.path, exc.detail,
            extra=safe_log_context(exc.context),
        )
        return JSONResponse(
            status_code=exc.http_status_code,
            content={"error_code": exc.error_code, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """
        Last-resort catch-all. Never leaks internal exception details
        (stack traces, DB errors) to the client — those go to logs only.
        """
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error_code": "INTERNAL_SERVER_ERROR", "detail": "An unexpected error occurred."},
        )
