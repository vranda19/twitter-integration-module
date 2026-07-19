"""
app/services/twitter_client.py

Low-level async HTTP wrapper around Twitter's API. Every other service
in this module (oauth, post, media, thread, analytics) goes through
THIS file to talk to Twitter — no service ever calls httpx directly.

WHY THIS LAYER EXISTS SEPARATELY FROM services/twitter_post_service.py etc:
1. Retry/backoff/rate-limit logic is identical regardless of WHICH
   Twitter endpoint is being called — writing it once here means every
   feature (posting, media, analytics) gets it for free.
2. Twitter API URL structure, auth header formatting, and error-shape
   parsing changes independently of our business logic. If Twitter
   changes their error envelope tomorrow, one file changes.
3. Testability — tests/mocks/twitter_api_mock.py mocks THIS class,
   so unit tests for post_service/media_service never make real HTTP calls.
"""

import asyncio
from typing import Any, Optional

import httpx

from app.config.settings import settings
from app.exceptions.twitter_exceptions import TwitterAPIError, TwitterRateLimitError
from app.utils.logger import get_logger, safe_log_context

logger = get_logger(__name__)

# Twitter API error codes that are safe to retry automatically —
# transient server-side issues, not our request being wrong.
_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


class TwitterAPIClient:
    """
    Thin async wrapper for authenticated calls to Twitter's REST API.

    One instance is created per-request (via dependency injection) with
    the CALLER'S decrypted bearer/access token — it is never a shared
    singleton, since different requests act on behalf of different
    connected Twitter accounts.
    """

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token
        self._base_url = settings.TWITTER_API_BASE_URL

    def _headers(self, *, content_type: str = "application/json") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": content_type,
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        """
        Executes an authenticated request against `{base_url}{path}` with
        automatic retry on transient failures and structured handling of
        rate limits.

        `idempotent` MUST be True only for safe-to-retry operations
        (GET requests, or POSTs we know are idempotent at the Twitter
        API level). We do NOT retry tweet-creation POSTs automatically
        here — a transient network failure after Twitter already
        accepted the tweet would otherwise cause a duplicate post.
        Retry-with-dedup for posting is handled explicitly in
        twitter_post_service.py using a client-side idempotency approach,
        not blind retries at this layer.
        """
        url = f"{self._base_url}{path}"
        last_exception: Optional[Exception] = None

        max_attempts = settings.HTTP_MAX_RETRIES if idempotent else 1

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=self._headers(),
                        json=json_body,
                        params=params,
                    )
            except httpx.RequestError as exc:
                last_exception = exc
                logger.warning(
                    "Network error calling Twitter (attempt %s/%s): %s", attempt, max_attempts, str(exc)
                )
                if attempt < max_attempts:
                    await asyncio.sleep(_backoff_delay(attempt))
                    continue
                raise TwitterAPIError(
                    "Failed to reach Twitter API after retries", context={"url": url}
                ) from exc

            if response.status_code == 429:
                retry_after = _extract_retry_after(response)
                logger.warning("Twitter rate limit hit on %s — retry_after=%ss", path, retry_after)
                raise TwitterRateLimitError(
                    "Twitter API rate limit exceeded",
                    retry_after_seconds=retry_after,
                    context={"path": path},
                )

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < max_attempts:
                logger.warning(
                    "Retryable Twitter error %s on %s (attempt %s/%s)",
                    response.status_code, path, attempt, max_attempts,
                )
                await asyncio.sleep(_backoff_delay(attempt))
                continue

            if response.status_code >= 400:
                error_body = _safe_json(response)
                logger.error(
                    "Twitter API error status=%s path=%s body=%s",
                    response.status_code, path, safe_log_context(error_body),
                )
                raise TwitterAPIError(
                    f"Twitter API returned {response.status_code}",
                    twitter_status_code=response.status_code,
                    context={"path": path, "body": error_body},
                )

            return _safe_json(response)

        # Unreachable in practice, but keeps type checkers satisfied.
        raise TwitterAPIError("Twitter API request failed", context={"url": url}) from last_exception

    async def upload_media(
        self,
        file_bytes: bytes,
        *,
        media_category: str,
        media_type: str,
    ) -> dict[str, Any]:
        """
        Uploads media via Twitter's chunked upload endpoint (v1.1 media
        upload — see note in twitter_media_service.py about why this
        specific endpoint still uses the legacy base URL).

        Implemented as INIT -> APPEND -> FINALIZE per Twitter's chunked
        upload protocol, required for anything larger than a few hundred KB
        (i.e., effectively required for GIFs and all videos, and safe to
        always use for images too for consistency).
        """
        upload_base = settings.TWITTER_UPLOAD_BASE_URL
        headers = {"Authorization": f"Bearer {self._access_token}"}

        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            # INIT — declare total size and category, get a media_id back
            init_response = await client.post(
                f"{upload_base}/media/upload.json",
                headers=headers,
                data={
                    "command": "INIT",
                    "total_bytes": len(file_bytes),
                    "media_type": media_type,
                    "media_category": media_category,
                },
            )
            if init_response.status_code >= 400:
                raise TwitterAPIError(
                    "Media upload INIT failed",
                    twitter_status_code=init_response.status_code,
                    context={"body": _safe_json(init_response)},
                )
            media_id = _safe_json(init_response)["media_id_string"]

            # APPEND — upload in chunks (5MB each, well under Twitter's limits)
            chunk_size = 5 * 1024 * 1024
            for segment_index, offset in enumerate(range(0, len(file_bytes), chunk_size)):
                chunk = file_bytes[offset : offset + chunk_size]
                append_response = await client.post(
                    f"{upload_base}/media/upload.json",
                    headers=headers,
                    data={"command": "APPEND", "media_id": media_id, "segment_index": segment_index},
                    files={"media": chunk},
                )
                if append_response.status_code >= 400:
                    raise TwitterAPIError(
                        "Media upload APPEND failed",
                        twitter_status_code=append_response.status_code,
                        context={"body": _safe_json(append_response), "segment_index": segment_index},
                    )

            # FINALIZE — tell Twitter the upload is complete
            finalize_response = await client.post(
                f"{upload_base}/media/upload.json",
                headers=headers,
                data={"command": "FINALIZE", "media_id": media_id},
            )
            if finalize_response.status_code >= 400:
                raise TwitterAPIError(
                    "Media upload FINALIZE failed",
                    twitter_status_code=finalize_response.status_code,
                    context={"body": _safe_json(finalize_response)},
                )

            finalize_body = _safe_json(finalize_response)

            # Video/GIF processing is asynchronous server-side — poll
            # STATUS until Twitter reports the media is ready to attach.
            processing_info = finalize_body.get("processing_info")
            if processing_info:
                finalize_body = await self._poll_media_processing(client, headers, media_id)

            return finalize_body

    async def _poll_media_processing(
        self, client: httpx.AsyncClient, headers: dict[str, str], media_id: str
    ) -> dict[str, Any]:
        """
        Polls Twitter's media STATUS command until a video/GIF finishes
        server-side transcoding, respecting Twitter's suggested
        `check_after_secs` wait between polls rather than hammering the
        endpoint.
        """
        upload_base = settings.TWITTER_UPLOAD_BASE_URL
        max_polls = 20

        for _ in range(max_polls):
            status_response = await client.get(
                f"{upload_base}/media/upload.json",
                headers=headers,
                params={"command": "STATUS", "media_id": media_id},
            )
            body = _safe_json(status_response)
            processing_info = body.get("processing_info", {})
            state = processing_info.get("state")

            if state == "succeeded":
                return body
            if state == "failed":
                raise TwitterAPIError(
                    "Twitter failed to process uploaded media",
                    context={"media_id": media_id, "body": body},
                )

            wait_seconds = processing_info.get("check_after_secs", 3)
            await asyncio.sleep(wait_seconds)

        raise TwitterAPIError("Media processing timed out", context={"media_id": media_id})


def _extract_retry_after(response: httpx.Response) -> Optional[int]:
    reset_header = response.headers.get("x-rate-limit-reset")
    if not reset_header:
        return None
    try:
        import time

        return max(int(reset_header) - int(time.time()), 1)
    except ValueError:
        return None


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {"raw_body": response.text}


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with a small base — 0.5s, 1s, 2s, 4s..."""
    return 0.5 * (2 ** (attempt - 1))
