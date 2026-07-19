"""
app/schemas/twitter_account_schema.py

Response contracts for account management endpoints
(GET /twitter/accounts, DELETE /twitter/accounts/{id}).

SECURITY NOTE: `TwitterAccountResponse` deliberately has NO fields for
access_token / refresh_token. This is enforced structurally — even if
a developer later carelessly does `**account_model.__dict__` somewhere,
Pydantic will simply ignore extra fields not declared here rather than
leak them, as long as routers construct this schema explicitly (which
is the pattern used throughout this module).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class TwitterAccountResponse(BaseModel):
    """Public-safe representation of a connected Twitter account."""

    id: str = Field(..., description="Internal UUID of this connection record.")
    twitter_user_id: str = Field(..., description="Twitter's numeric user ID.")
    username: str = Field(..., description="Twitter @handle, without the @.", examples=["jdoe"])
    display_name: str = Field(..., examples=["Jane Doe"])
    profile_image_url: str | None = Field(default=None)
    scope: str = Field(..., description="Space-separated OAuth scopes granted.")
    is_active: bool = Field(..., description="False if the connection was disconnected or tokens revoked.")
    connected_at: datetime = Field(..., description="When this account was first connected.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "b3f1c2a4-1234-4a5b-9c3d-abcdef123456",
                    "twitter_user_id": "1489732451",
                    "username": "jdoe",
                    "display_name": "Jane Doe",
                    "profile_image_url": "https://pbs.twimg.com/profile_images/xyz/avatar.jpg",
                    "scope": "tweet.read tweet.write users.read offline.access",
                    "is_active": True,
                    "connected_at": "2026-07-01T10:15:00Z",
                }
            ]
        }
    }


class TwitterAccountListResponse(BaseModel):
    """Returned by GET /twitter/accounts — supports multiple connected accounts per user."""

    accounts: list[TwitterAccountResponse]
    total: int


class TwitterAccountDisconnectResponse(BaseModel):
    """Returned by DELETE /twitter/accounts/{id}."""

    id: str
    disconnected: bool = True
    message: str = "Twitter account disconnected successfully."
