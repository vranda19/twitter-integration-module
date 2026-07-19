"""
app/exceptions/twitter_exceptions.py

Custom exception hierarchy for the Twitter integration module.

WHY CUSTOM EXCEPTIONS INSTEAD OF FastAPI's HTTPException:
Services in this module must stay ignorant of HTTP. A service raises
`TokenExpiredError`; it has no idea (and shouldn't care) that this will
eventually become a 401 JSON response. That translation happens exactly
once, in app/middleware/error_handler.py.

This also makes services reusable outside of an HTTP request context —
e.g. a future Celery beat task (owned by another teammate, per Part 10)
can call `TwitterPostService.post_tweet(...)` directly and catch these
same exceptions, without ever touching FastAPI.
"""

from typing import Any, Optional


class TwitterBaseError(Exception):
    """
    Base class for all exceptions raised by this module.

    `detail` is a human-readable message safe to show to the end user
    (never includes tokens, secrets, or raw provider payloads).
    `context` holds extra structured data for logging only — the error
    handler middleware must NEVER serialize `context` directly into an
    HTTP response, only into logs.
    """

    http_status_code: int = 500
    error_code: str = "TWITTER_ERROR"

    def __init__(self, detail: str, context: Optional[dict[str, Any]] = None) -> None:
        self.detail = detail
        self.context = context or {}
        super().__init__(detail)


class TwitterAuthError(TwitterBaseError):
    """Raised when OAuth login/callback/authorization fails."""

    http_status_code = 401
    error_code = "TWITTER_AUTH_ERROR"


class InvalidOAuthStateError(TwitterAuthError):
    """Raised when the `state` param on callback doesn't match what we issued (CSRF defense)."""

    http_status_code = 400
    error_code = "TWITTER_INVALID_STATE"


class TokenExpiredError(TwitterBaseError):
    """Raised when an access token is expired and cannot be silently refreshed."""

    http_status_code = 401
    error_code = "TWITTER_TOKEN_EXPIRED"


class TokenRefreshError(TwitterBaseError):
    """Raised when the refresh-token exchange with Twitter fails (e.g. refresh token revoked)."""

    http_status_code = 401
    error_code = "TWITTER_TOKEN_REFRESH_FAILED"


class TwitterAccountNotFoundError(TwitterBaseError):
    """Raised when a requested twitter_accounts row doesn't exist or doesn't belong to the user."""

    http_status_code = 404
    error_code = "TWITTER_ACCOUNT_NOT_FOUND"


class TwitterRateLimitError(TwitterBaseError):
    """
    Raised when Twitter returns HTTP 429.

    `retry_after_seconds` is read from the `x-rate-limit-reset` header
    so callers (and the error middleware) can surface a precise
    "try again in N seconds" message instead of a generic failure.
    """

    http_status_code = 429
    error_code = "TWITTER_RATE_LIMITED"

    def __init__(
        self,
        detail: str,
        retry_after_seconds: Optional[int] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail, context)


class TwitterAPIError(TwitterBaseError):
    """
    Generic catch-all for non-2xx responses from Twitter's API that
    aren't auth or rate-limit specific (e.g. malformed tweet, 5xx from Twitter).
    """

    http_status_code = 502
    error_code = "TWITTER_API_ERROR"

    def __init__(
        self,
        detail: str,
        twitter_status_code: Optional[int] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        self.twitter_status_code = twitter_status_code
        super().__init__(detail, context)


class MediaUploadError(TwitterBaseError):
    """Raised when image/GIF/video upload to Twitter fails."""

    http_status_code = 502
    error_code = "TWITTER_MEDIA_UPLOAD_ERROR"


class ThreadPostingError(TwitterBaseError):
    """
    Raised when posting a multi-tweet thread fails partway through.

    `posted_tweet_ids` carries the IDs that succeeded BEFORE the failure,
    so the service layer can attempt rollback (deletion) and the caller
    can be told exactly what state Twitter is left in.
    """

    http_status_code = 502
    error_code = "TWITTER_THREAD_POSTING_ERROR"

    def __init__(
        self,
        detail: str,
        posted_tweet_ids: Optional[list[str]] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        self.posted_tweet_ids = posted_tweet_ids or []
        super().__init__(detail, context)


class TwitterValidationError(TwitterBaseError):
    """Raised for request-shape problems caught before hitting Twitter's API (e.g. empty thread)."""

    http_status_code = 422
    error_code = "TWITTER_VALIDATION_ERROR"
