"""
app/models/twitter_account_model.py

Typed internal representation of a row in the `twitter_accounts` table.

WHY THIS IS SEPARATE FROM app/schemas/:
Schemas define what crosses the HTTP boundary (JSON in/out). This model
defines what the DATABASE stores, including fields (encrypted tokens)
that must NEVER be serialized into an API response. Repositories return
this model; services convert it into a response schema before it ever
reaches a router.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True, slots=True)
class TwitterAccountModel:
    """
    Immutable representation of one connected Twitter account.

    `access_token` and `refresh_token` here are ALWAYS the ENCRYPTED
    ciphertext exactly as stored in Postgres — decryption happens only
    at the point of use, inside services/twitter_token_service.py.
    """

    id: str
    user_id: str
    twitter_user_id: str
    username: str
    display_name: str
    profile_image_url: Optional[str]
    access_token: str  # encrypted ciphertext
    refresh_token: Optional[str]  # encrypted ciphertext, None if offline.access wasn't granted
    scope: str
    expires_at: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_db_row(row: dict) -> "TwitterAccountModel":
        """
        Builds a model instance from a raw Supabase/Postgres row (dict).

        Centralizing this parsing means if a column is renamed or a type
        changes, exactly one function needs updating.
        """
        return TwitterAccountModel(
            id=row["id"],
            user_id=row["user_id"],
            twitter_user_id=row["twitter_user_id"],
            username=row["username"],
            display_name=row["display_name"],
            profile_image_url=row.get("profile_image_url"),
            access_token=row["access_token"],
            refresh_token=row.get("refresh_token"),
            scope=row["scope"],
            expires_at=_parse_datetime(row["expires_at"]),
            is_active=row["is_active"],
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
        )


def _parse_datetime(value: object) -> datetime:
    """Supabase returns ISO-8601 strings over REST; normalize to datetime consistently."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
