"""
app/repositories/twitter_account_repository.py

The ONLY file in this module allowed to run queries against the
`twitter_accounts` table. Services never call Supabase directly —
they call this repository, so that:
  1. If we ever swap Supabase's client for raw SQLAlchemy, exactly one
     file changes.
  2. Every query is guaranteed to be scoped by `user_id` (since RLS is
     bypassed via the service-role key — see core/supabase_client.py).
  3. Services can be unit-tested by mocking this repository entirely,
     with zero real network/database calls.

Tokens are stored and returned here EXACTLY as encrypted ciphertext.
This repository never encrypts or decrypts — that responsibility
belongs to services/twitter_token_service.py, keeping this file a pure
data-access layer.
"""

from datetime import datetime, timezone
from typing import Optional

from supabase import Client

from app.models.twitter_account_model import TwitterAccountModel
from app.utils.logger import get_logger

logger = get_logger(__name__)

TABLE_NAME = "twitter_accounts"


class TwitterAccountRepository:
    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    async def create(
        self,
        *,
        user_id: str,
        twitter_user_id: str,
        username: str,
        display_name: str,
        profile_image_url: Optional[str],
        encrypted_access_token: str,
        encrypted_refresh_token: Optional[str],
        scope: str,
        expires_at: datetime,
    ) -> TwitterAccountModel:
        """
        Inserts a new connected account row. Called after a successful
        OAuth callback exchange for a twitter_user_id we haven't seen
        before for this user.
        """
        payload = {
            "user_id": user_id,
            "twitter_user_id": twitter_user_id,
            "username": username,
            "display_name": display_name,
            "profile_image_url": profile_image_url,
            "access_token": encrypted_access_token,
            "refresh_token": encrypted_refresh_token,
            "scope": scope,
            "expires_at": expires_at.isoformat(),
            "is_active": True,
        }
        response = self._db.table(TABLE_NAME).insert(payload).execute()
        row = response.data[0]
        logger.info("Created twitter_accounts row id=%s user_id=%s", row["id"], user_id)
        return TwitterAccountModel.from_db_row(row)

    async def get_by_id(self, account_id: str, user_id: str) -> Optional[TwitterAccountModel]:
        """
        Fetches a single account, scoped to the requesting user.
        Returns None if it doesn't exist OR belongs to a different user
        (deliberately indistinguishable from the caller's perspective —
        prevents account-ID enumeration leaking existence info).
        """
        response = (
            self._db.table(TABLE_NAME)
            .select("*")
            .eq("id", account_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return TwitterAccountModel.from_db_row(response.data[0])

    async def get_by_twitter_user_id(self, twitter_user_id: str, user_id: str) -> Optional[TwitterAccountModel]:
        """
        Used during OAuth callback to detect "user is reconnecting an
        already-linked Twitter account" vs "user is linking a new one".
        """
        response = (
            self._db.table(TABLE_NAME)
            .select("*")
            .eq("twitter_user_id", twitter_user_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return TwitterAccountModel.from_db_row(response.data[0])

    async def list_by_user(self, user_id: str, *, only_active: bool = True) -> list[TwitterAccountModel]:
        """Supports the 'multiple Twitter accounts per user' requirement — returns all connections."""
        query = self._db.table(TABLE_NAME).select("*").eq("user_id", user_id)
        if only_active:
            query = query.eq("is_active", True)
        response = query.order("created_at", desc=True).execute()
        return [TwitterAccountModel.from_db_row(row) for row in response.data]

    async def update_tokens(
        self,
        account_id: str,
        *,
        encrypted_access_token: str,
        encrypted_refresh_token: Optional[str],
        expires_at: datetime,
    ) -> TwitterAccountModel:
        """
        Called by the token refresh flow (Part 5) after successfully
        exchanging a refresh_token for a new access_token.
        """
        payload = {
            "access_token": encrypted_access_token,
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Twitter may or may not rotate the refresh token on each refresh;
        # only overwrite it if a new one was actually returned.
        if encrypted_refresh_token is not None:
            payload["refresh_token"] = encrypted_refresh_token

        response = self._db.table(TABLE_NAME).update(payload).eq("id", account_id).execute()
        logger.info("Refreshed tokens for twitter_accounts id=%s", account_id)
        return TwitterAccountModel.from_db_row(response.data[0])

    async def reactivate_with_new_tokens(
        self,
        account_id: str,
        *,
        encrypted_access_token: str,
        encrypted_refresh_token: Optional[str],
        scope: str,
        expires_at: datetime,
    ) -> TwitterAccountModel:
        """
        Called when a user "reconnects" an account they had previously
        disconnected — flips is_active back to True and stores fresh
        tokens rather than creating a duplicate row.
        """
        payload = {
            "access_token": encrypted_access_token,
            "refresh_token": encrypted_refresh_token,
            "scope": scope,
            "expires_at": expires_at.isoformat(),
            "is_active": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        response = self._db.table(TABLE_NAME).update(payload).eq("id", account_id).execute()
        logger.info("Reactivated twitter_accounts id=%s", account_id)
        return TwitterAccountModel.from_db_row(response.data[0])

    async def deactivate(self, account_id: str, user_id: str) -> bool:
        """
        Soft-deletes a connection (disconnect). We keep the row (with
        is_active=False) rather than hard-deleting, preserving audit
        history of what was posted while it was connected.
        """
        response = (
            self._db.table(TABLE_NAME)
            .update({"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", account_id)
            .eq("user_id", user_id)
            .execute()
        )
        deactivated = len(response.data) > 0
        if deactivated:
            logger.info("Deactivated twitter_accounts id=%s user_id=%s", account_id, user_id)
        return deactivated
