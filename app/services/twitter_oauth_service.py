"""
app/services/twitter_oauth_service.py

Business logic for the OAuth 2.0 Authorization Code + PKCE flow:
  1. build_authorize_url() — used by GET /twitter/login
  2. handle_callback()     — used by GET /twitter/callback

WHY THIS IS A SEPARATE SERVICE FROM twitter_token_service.py:
This service handles the ONE-TIME login/link flow (user explicitly
authorizing our app). twitter_token_service.py handles the ONGOING
silent refresh flow (no user interaction, runs before every API call).
Different triggers, different failure semantics — splitting them keeps
each file focused and independently testable.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config.settings import settings
from app.core.redis_client import UpstashRedisClient
from app.core.security import encrypt_token
from app.exceptions.twitter_exceptions import InvalidOAuthStateError, TwitterAuthError
from app.repositories.twitter_account_repository import TwitterAccountRepository
from app.schemas.twitter_account_schema import TwitterAccountResponse
from app.utils.logger import get_logger, safe_log_context
from app.utils.oauth_pkce import generate_csrf_state, generate_pkce_pair

logger = get_logger(__name__)

_STATE_KEY_PREFIX = "twitter:oauth:state:"


class TwitterOAuthService:
    def __init__(
        self,
        redis_client: UpstashRedisClient,
        account_repository: TwitterAccountRepository,
    ) -> None:
        self._redis = redis_client
        self._accounts = account_repository

    async def build_authorize_url(self, user_id: str) -> str:
        """
        Step 1 of OAuth: generates state + PKCE pair, stores them in
        Redis keyed by state (TTL-bound), and returns the full Twitter
        authorize URL for the frontend to redirect the browser to.

        WHY WE STORE `user_id` ALONGSIDE state/verifier:
        The callback endpoint is hit by Twitter's redirect, which
        carries no Supabase session context of its own (it's a
        server-to-browser-to-server hop). Binding user_id to the state
        value we control is what lets the callback know WHICH of our
        users just authorized their Twitter account, without trusting
        any user-supplied identifier in the callback request itself.
        """
        state = generate_csrf_state()
        code_verifier, code_challenge = generate_pkce_pair()

        await self._redis.set_json(
            key=f"{_STATE_KEY_PREFIX}{state}",
            value={"user_id": user_id, "code_verifier": code_verifier},
            ttl_seconds=settings.OAUTH_STATE_TTL_SECONDS,
        )

        query_params = {
            "response_type": "code",
            "client_id": settings.TWITTER_CLIENT_ID,
            "redirect_uri": settings.TWITTER_REDIRECT_URI,
            "scope": settings.TWITTER_OAUTH_SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        authorize_url = f"{settings.TWITTER_AUTHORIZE_URL}?{urlencode(query_params)}"

        logger.info("Generated Twitter authorize URL for user_id=%s", user_id)
        return authorize_url

    async def handle_callback(self, *, code: str, state: str) -> TwitterAccountResponse:
        """
        Step 2 of OAuth: validates state, exchanges the authorization
        code for tokens, fetches the connected Twitter profile, encrypts
        and persists tokens, and returns the account summary.

        Raises InvalidOAuthStateError if `state` doesn't match anything
        we issued (expired, already consumed, or forged) — this IS the
        CSRF defense for this flow.
        """
        state_data = await self._redis.get_json(f"{_STATE_KEY_PREFIX}{state}")
        if state_data is None:
            logger.warning("OAuth callback with unknown/expired state=%s", state)
            raise InvalidOAuthStateError("OAuth state is invalid or has expired. Please try connecting again.")

        # Consume the state immediately — single use only, prevents replay.
        await self._redis.delete(f"{_STATE_KEY_PREFIX}{state}")

        user_id = state_data["user_id"]
        code_verifier = state_data["code_verifier"]

        token_response = await self._exchange_code_for_tokens(code=code, code_verifier=code_verifier)
        profile = await self._fetch_twitter_profile(token_response["access_token"])

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_response["expires_in"])
        encrypted_access_token = encrypt_token(token_response["access_token"])
        encrypted_refresh_token = (
            encrypt_token(token_response["refresh_token"]) if "refresh_token" in token_response else None
        )

        existing = await self._accounts.get_by_twitter_user_id(profile["id"], user_id)

        if existing is not None:
            account = await self._accounts.reactivate_with_new_tokens(
                existing.id,
                encrypted_access_token=encrypted_access_token,
                encrypted_refresh_token=encrypted_refresh_token,
                scope=token_response.get("scope", settings.TWITTER_OAUTH_SCOPES),
                expires_at=expires_at,
            )
            logger.info("Reconnected existing Twitter account id=%s for user_id=%s", account.id, user_id)
        else:
            account = await self._accounts.create(
                user_id=user_id,
                twitter_user_id=profile["id"],
                username=profile["username"],
                display_name=profile["name"],
                profile_image_url=profile.get("profile_image_url"),
                encrypted_access_token=encrypted_access_token,
                encrypted_refresh_token=encrypted_refresh_token,
                scope=token_response.get("scope", settings.TWITTER_OAUTH_SCOPES),
                expires_at=expires_at,
            )
            logger.info("Created new Twitter account id=%s for user_id=%s", account.id, user_id)

        return TwitterAccountResponse(
            id=account.id,
            twitter_user_id=account.twitter_user_id,
            username=account.username,
            display_name=account.display_name,
            profile_image_url=account.profile_image_url,
            scope=account.scope,
            is_active=account.is_active,
            connected_at=account.created_at,
        )

    async def _exchange_code_for_tokens(self, *, code: str, code_verifier: str) -> dict:
        """
        Exchanges the short-lived authorization `code` for an
        access_token (+ refresh_token if offline.access was granted).

        Uses HTTP Basic Auth with client_id:client_secret per Twitter's
        OAuth 2.0 confidential client spec, PLUS the PKCE code_verifier
        in the body — Twitter requires both for server-side (non-PKCE-only)
        confidential clients.
        """
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.TWITTER_REDIRECT_URI,
            "code_verifier": code_verifier,
            "client_id": settings.TWITTER_CLIENT_ID,
        }

        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                settings.TWITTER_TOKEN_URL,
                data=payload,
                auth=(settings.TWITTER_CLIENT_ID, settings.TWITTER_CLIENT_SECRET),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            logger.error(
                "Token exchange failed status=%s body=%s",
                response.status_code,
                safe_log_context(_try_json(response)),
            )
            raise TwitterAuthError("Failed to exchange authorization code with Twitter.")

        return response.json()

    async def _fetch_twitter_profile(self, access_token: str) -> dict:
        """Fetches the connected user's Twitter profile (id, username, name, avatar) right after token exchange."""
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{settings.TWITTER_API_BASE_URL}/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"user.fields": "profile_image_url"},
            )

        if response.status_code != 200:
            logger.error("Failed to fetch Twitter profile status=%s", response.status_code)
            raise TwitterAuthError("Failed to fetch Twitter profile after authorization.")

        return response.json()["data"]


def _try_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"raw_body": response.text}
