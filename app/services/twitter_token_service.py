"""
app/services/twitter_token_service.py

Handles automatic access-token refresh so users never have to manually
re-login once they've connected their account (as long as offline.access
was granted and the refresh token hasn't been revoked on Twitter's side).

THIS FILE IS THE SINGLE ENTRYPOINT every other service uses to obtain a
usable, decrypted, guaranteed-non-expired access token. Nobody else in
this module reads `account.access_token` directly — they call
`get_valid_access_token()`. This guarantees the refresh check happens
consistently everywhere, instead of being re-implemented (or forgotten)
in post_service, media_service, analytics_service independently.
"""

from datetime import datetime, timedelta, timezone

import httpx

from app.config.settings import settings
from app.core.security import decrypt_token, encrypt_token
from app.exceptions.twitter_exceptions import TokenRefreshError, TwitterAccountNotFoundError
from app.repositories.twitter_account_repository import TwitterAccountRepository
from app.utils.logger import get_logger, safe_log_context

logger = get_logger(__name__)

# Refresh proactively if the token expires within this window, rather
# than waiting for it to fully expire — avoids a race where a post
# request starts with a token that expires mid-flight.
_EXPIRY_SAFETY_MARGIN = timedelta(minutes=5)


class TwitterTokenService:
    def __init__(self, account_repository: TwitterAccountRepository) -> None:
        self._accounts = account_repository

    async def get_valid_access_token(self, account_id: str, user_id: str) -> str:
        """
        Returns a decrypted, currently-valid access token for the given
        connected account, transparently refreshing it first if it's
        expired or about to expire.

        Every service that calls the Twitter API (posting, media,
        analytics) calls THIS function first — never reads the stored
        token directly.
        """
        account = await self._accounts.get_by_id(account_id, user_id)
        if account is None or not account.is_active:
            raise TwitterAccountNotFoundError("Twitter account not found or has been disconnected.")

        expires_soon = datetime.now(timezone.utc) >= (account.expires_at - _EXPIRY_SAFETY_MARGIN)

        if not expires_soon:
            return decrypt_token(account.access_token)

        if account.refresh_token is None:
            # No refresh token means offline.access wasn't granted at
            # connect time — the only path forward is asking the user
            # to reconnect (re-run the full OAuth flow).
            logger.warning("Access token expired with no refresh_token for account_id=%s", account_id)
            raise TokenRefreshError(
                "Twitter session expired and cannot be refreshed automatically. Please reconnect this account."
            )

        logger.info("Access token expiring soon for account_id=%s — refreshing", account_id)
        return await self._refresh_and_persist(account_id, account.refresh_token)

    async def _refresh_and_persist(self, account_id: str, encrypted_refresh_token: str) -> str:
        """
        Exchanges the refresh_token for a new access_token (and possibly
        a rotated refresh_token — Twitter may issue a new one each time),
        persists the new encrypted tokens, and returns the new plaintext
        access token for immediate use.
        """
        refresh_token = decrypt_token(encrypted_refresh_token)

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
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
                "Token refresh failed for account_id=%s status=%s body=%s",
                account_id,
                response.status_code,
                safe_log_context(_try_json(response)),
            )
            # A refresh failure most commonly means the user revoked
            # access from Twitter's side ("Apps and sessions" settings).
            # We deliberately do NOT deactivate the account automatically
            # here — surface the error and let the user explicitly
            # reconnect, which is clearer UX than silently disabling
            # a connection they didn't consciously remove.
            raise TokenRefreshError(
                "Failed to refresh Twitter access token. The connection may have been revoked — please reconnect."
            )

        token_data = response.json()
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

        new_encrypted_access_token = encrypt_token(token_data["access_token"])
        new_encrypted_refresh_token = (
            encrypt_token(token_data["refresh_token"]) if "refresh_token" in token_data else None
        )

        await self._accounts.update_tokens(
            account_id,
            encrypted_access_token=new_encrypted_access_token,
            encrypted_refresh_token=new_encrypted_refresh_token,
            expires_at=new_expires_at,
        )

        logger.info("Successfully refreshed access token for account_id=%s", account_id)
        return token_data["access_token"]


def _try_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"raw_body": response.text}
