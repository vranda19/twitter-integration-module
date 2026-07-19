"""
app/core/redis_client.py

Thin async wrapper around Upstash Redis's REST API, used exclusively
by this module to store short-lived OAuth `state` + PKCE `code_verifier`
pairs between the /twitter/login redirect and the /twitter/callback.

WHY REDIS INSTEAD OF THE DATABASE FOR THIS:
OAuth state is inherently ephemeral (valid for ~10 minutes) and is
never queried by anything except the callback that immediately consumes
it. Writing it to Postgres would mean a table full of dead rows needing
cleanup jobs. Redis's native TTL (`EX` seconds) handles expiry for free,
and this module's stack already includes Upstash Redis for Celery — we
reuse the same instance for state storage.

WHY THE REST API AND NOT a raw redis-py TCP client:
Upstash Redis is designed to be accessed over HTTPS REST from serverless
/ edge-friendly backends, and using the REST client keeps this module
consistent regardless of whether the FastAPI service runs in a
traditional long-lived container or a serverless function later.
"""

import json
from typing import Any, Optional

import httpx

from app.config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class UpstashRedisClient:
    """
    Minimal async client for the subset of Redis commands this module
    needs: SET with expiry, GET, and DEL.
    """

    def __init__(self) -> None:
        self._base_url = settings.UPSTASH_REDIS_REST_URL.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.UPSTASH_REDIS_REST_TOKEN}",
        }

    async def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        """Stores `value` as JSON under `key`, expiring after `ttl_seconds`."""
        serialized = json.dumps(value)
        url = f"{self._base_url}/set/{key}"
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers=self._headers,
                params={"EX": ttl_seconds},
                content=serialized,
            )
        if response.status_code != 200:
            logger.error("Upstash SET failed for key=%s status=%s", key, response.status_code)
            raise RuntimeError("Failed to persist OAuth state to Redis")

    async def get_json(self, key: str) -> Optional[dict[str, Any]]:
        """Fetches and JSON-decodes the value stored under `key`, or None if absent/expired."""
        url = f"{self._base_url}/get/{key}"
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=self._headers)

        if response.status_code != 200:
            logger.error("Upstash GET failed for key=%s status=%s", key, response.status_code)
            return None

        payload = response.json()
        raw_value = payload.get("result")
        if raw_value is None:
            return None
        return json.loads(raw_value)

    async def delete(self, key: str) -> None:
        """Deletes `key` — used to consume OAuth state exactly once (single-use CSRF token)."""
        url = f"{self._base_url}/del/{key}"
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=self._headers)
        if response.status_code != 200:
            logger.warning("Upstash DEL failed for key=%s status=%s", key, response.status_code)


def get_redis_client() -> UpstashRedisClient:
    """FastAPI dependency factory — see app/api/deps.py."""
    return UpstashRedisClient()
