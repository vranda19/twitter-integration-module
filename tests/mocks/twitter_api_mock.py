"""
tests/mocks/twitter_api_mock.py

Fake Twitter API response payloads and a mock TwitterAPIClient used
across unit tests. Ensures unit tests NEVER make real network calls to
Twitter — required for fast, deterministic CI runs and to avoid burning
real Twitter API rate-limit quota from automated tests.
"""

from typing import Any, Optional
from unittest.mock import AsyncMock


def mock_token_exchange_response() -> dict[str, Any]:
    return {
        "token_type": "bearer",
        "expires_in": 7200,
        "access_token": "MOCK_ACCESS_TOKEN_abc123",
        "refresh_token": "MOCK_REFRESH_TOKEN_xyz789",
        "scope": "tweet.read tweet.write users.read offline.access",
    }


def mock_twitter_profile_response() -> dict[str, Any]:
    return {
        "data": {
            "id": "1489732451",
            "username": "jdoe",
            "name": "Jane Doe",
            "profile_image_url": "https://pbs.twimg.com/profile_images/xyz/avatar.jpg",
        }
    }


def mock_tweet_create_response(tweet_id: str = "1815938201938472960", text: str = "Hello world") -> dict[str, Any]:
    return {"data": {"id": tweet_id, "text": text}}


def mock_tweet_metrics_response(tweet_id: str = "1815938201938472960") -> dict[str, Any]:
    return {
        "data": {
            "id": tweet_id,
            "public_metrics": {
                "like_count": 142,
                "retweet_count": 18,
                "reply_count": 7,
                "quote_count": 3,
                "bookmark_count": 26,
            },
            "non_public_metrics": {"impression_count": 5230},
        }
    }


def mock_media_finalize_response(media_id: str = "1745938201938472960") -> dict[str, Any]:
    return {"media_id_string": media_id, "media_key": f"3_{media_id}"}


class FakeTwitterAPIClient:
    """
    Drop-in replacement for app.services.twitter_client.TwitterAPIClient.

    Services depend on `request(...)` and `upload_media(...)` methods —
    this fake implements both, returning queued responses in order so
    tests can simulate multi-step flows (e.g. a thread of 3 tweets).
    """

    def __init__(self, responses: Optional[list[dict[str, Any]]] = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self.request = AsyncMock(side_effect=self._handle_request)
        self.upload_media = AsyncMock(return_value=mock_media_finalize_response())

    async def _handle_request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        self.calls.append({"method": method, "path": path, **kwargs})
        if self._responses:
            return self._responses.pop(0)
        return mock_tweet_create_response()
