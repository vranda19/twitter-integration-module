"""
app/services/twitter_media_service.py

Handles uploading images, GIFs, and videos to Twitter so they can be
attached to a tweet or thread by media_id.

IMPORTANT AUTH NOTE (re-verify at implementation time, flagged since Part 2):
Twitter's media upload endpoint historically lived under the v1.1 API
(upload.twitter.com) and in practice still requires it for anything
beyond simple images — this module authenticates media uploads with the
connected account's OAuth 2.0 user-context bearer token, which Twitter
does accept on the v1.1 upload endpoint for apps configured with
OAuth 2.0 user context. If your team observes 403s specifically on
video/GIF upload in production, the fallback is OAuth 1.0a user-context
signing (HMAC-SHA1 with TWITTER_API_KEY / TWITTER_API_KEY_SECRET plus a
per-user OAuth 1.0a access token/secret pair) — this would require
capturing an OAuth 1.0a token during connect, which the current OAuth
2.0-only flow does not do. Flagging this explicitly rather than silently
guessing, since Twitter has changed this requirement before.
"""

from app.exceptions.twitter_exceptions import MediaUploadError, TwitterValidationError
from app.schemas.twitter_post_schema import MediaUploadResponse
from app.services.twitter_client import TwitterAPIClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_ALLOWED_GIF_TYPES = {"image/gif"}
_ALLOWED_VIDEO_TYPES = {"video/mp4"}

_MAX_IMAGE_BYTES = 5 * 1024 * 1024        # 5 MB
_MAX_GIF_BYTES = 15 * 1024 * 1024         # 15 MB
_MAX_VIDEO_BYTES = 512 * 1024 * 1024      # 512 MB


class TwitterMediaService:
    def __init__(self, client: TwitterAPIClient) -> None:
        self._client = client

    async def upload_media(self, *, file_bytes: bytes, content_type: str) -> MediaUploadResponse:
        """
        Validates the file against Twitter's constraints for its media
        type, uploads it (chunked INIT/APPEND/FINALIZE handled in
        twitter_client.py), and returns the resulting media_id.
        """
        media_category, size_limit = self._classify(content_type)

        if len(file_bytes) > size_limit:
            raise TwitterValidationError(
                f"File exceeds the maximum allowed size for {content_type} "
                f"({size_limit // (1024 * 1024)}MB)."
            )
        if len(file_bytes) == 0:
            raise TwitterValidationError("Uploaded file is empty.")

        logger.info("Uploading media content_type=%s size_bytes=%s", content_type, len(file_bytes))

        try:
            result = await self._client.upload_media(
                file_bytes, media_category=media_category, media_type=content_type
            )
        except Exception as exc:  # noqa: BLE001 — re-raised as a domain-specific error below
            logger.error("Media upload failed: %s", str(exc))
            raise MediaUploadError("Failed to upload media to Twitter.") from exc

        return MediaUploadResponse(
            media_id=result["media_id_string"],
            media_key=result.get("media_key"),
            media_type=content_type,
        )

    @staticmethod
    def _classify(content_type: str) -> tuple[str, int]:
        """Returns (twitter_media_category, max_allowed_bytes) for the given content type."""
        if content_type in _ALLOWED_IMAGE_TYPES:
            return "tweet_image", _MAX_IMAGE_BYTES
        if content_type in _ALLOWED_GIF_TYPES:
            return "tweet_gif", _MAX_GIF_BYTES
        if content_type in _ALLOWED_VIDEO_TYPES:
            return "tweet_video", _MAX_VIDEO_BYTES

        raise TwitterValidationError(
            f"Unsupported media type '{content_type}'. Allowed: "
            f"{sorted(_ALLOWED_IMAGE_TYPES | _ALLOWED_GIF_TYPES | _ALLOWED_VIDEO_TYPES)}"
        )
