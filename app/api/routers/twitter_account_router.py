"""
app/api/routers/twitter_account_router.py

HTTP endpoints for managing already-connected Twitter accounts:
  GET    /twitter/accounts       -> list all connected accounts for the user
  DELETE /twitter/accounts/{id}  -> disconnect one account

Reconnecting an account is intentionally NOT a separate endpoint here —
it's the exact same GET /twitter/login -> callback flow (see
twitter_auth_router.py), which the oauth service already handles by
reactivating an existing row when it detects a matching twitter_user_id.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_account_service, get_current_user_id
from app.schemas.twitter_account_schema import (
    TwitterAccountDisconnectResponse,
    TwitterAccountListResponse,
)
from app.services.twitter_account_service import TwitterAccountService

router = APIRouter(prefix="/twitter/accounts", tags=["Twitter - Accounts"])


@router.get(
    "",
    response_model=TwitterAccountListResponse,
    summary="List connected Twitter accounts",
    description="Returns every active Twitter account the current user has connected. Supports multiple accounts per user.",
)
async def list_twitter_accounts(
    user_id: Annotated[str, Depends(get_current_user_id)],
    account_service: Annotated[TwitterAccountService, Depends(get_account_service)],
) -> TwitterAccountListResponse:
    return await account_service.list_accounts(user_id)


@router.delete(
    "/{account_id}",
    response_model=TwitterAccountDisconnectResponse,
    summary="Disconnect a Twitter account",
    description="Soft-disconnects the specified Twitter account. It can be reconnected later via /twitter/login.",
)
async def disconnect_twitter_account(
    account_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    account_service: Annotated[TwitterAccountService, Depends(get_account_service)],
) -> TwitterAccountDisconnectResponse:
    return await account_service.disconnect_account(account_id, user_id)
