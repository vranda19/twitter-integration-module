"""
app/services/twitter_account_service.py

Business logic for managing already-connected Twitter accounts:
listing them and disconnecting them. Connecting/reconnecting is
handled by twitter_oauth_service.py (it's part of the OAuth flow) —
this service is deliberately narrow: read + soft-delete only.
"""

from app.exceptions.twitter_exceptions import TwitterAccountNotFoundError
from app.repositories.twitter_account_repository import TwitterAccountRepository
from app.schemas.twitter_account_schema import (
    TwitterAccountDisconnectResponse,
    TwitterAccountListResponse,
    TwitterAccountResponse,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TwitterAccountService:
    def __init__(self, account_repository: TwitterAccountRepository) -> None:
        self._accounts = account_repository

    async def list_accounts(self, user_id: str) -> TwitterAccountListResponse:
        """Supports multiple connected Twitter accounts per user — returns all active ones."""
        accounts = await self._accounts.list_by_user(user_id, only_active=True)
        response_items = [
            TwitterAccountResponse(
                id=account.id,
                twitter_user_id=account.twitter_user_id,
                username=account.username,
                display_name=account.display_name,
                profile_image_url=account.profile_image_url,
                scope=account.scope,
                is_active=account.is_active,
                connected_at=account.created_at,
            )
            for account in accounts
        ]
        return TwitterAccountListResponse(accounts=response_items, total=len(response_items))

    async def disconnect_account(self, account_id: str, user_id: str) -> TwitterAccountDisconnectResponse:
        """
        Soft-disconnects an account (is_active=False). We intentionally
        do NOT call Twitter's /oauth2/revoke endpoint automatically here —
        revoking server-side would silently break the connection from
        the user's own Twitter "Connected Apps" view without them
        expecting it in some flows. If your product wants immediate
        provider-side revocation on disconnect, call
        TwitterTokenService + the revoke endpoint explicitly here; noting
        it as a deliberate, reviewable product decision rather than a
        silent default.
        """
        existing = await self._accounts.get_by_id(account_id, user_id)
        if existing is None:
            raise TwitterAccountNotFoundError("Twitter account not found.")

        await self._accounts.deactivate(account_id, user_id)
        logger.info("User %s disconnected Twitter account %s", user_id, account_id)

        return TwitterAccountDisconnectResponse(id=account_id)
