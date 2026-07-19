"""
app/api/deps.py

FastAPI `Depends()` factory functions — the composition layer that
wires repositories into services and services into routers.

WHY THIS FILE EXISTS SEPARATELY:
Routers should never do `TwitterPostService(TwitterAPIClient(token), TwitterPostRepository(get_supabase_client()))`
inline — that couples routers to concrete implementations and makes
testing impossible without a real database and real Twitter API. By
routing every dependency through `Depends(get_x)`, tests can override
any single dependency (e.g. `app.dependency_overrides[get_post_service] = lambda: FakePostService()`)
without touching router code at all.

Dependency chain for authenticated, account-scoped operations:
  get_current_user_id → get_twitter_account_repository → get_token_service
  → get_authenticated_twitter_client (needs a specific account_id from
    the request) → get_post_service / get_media_service / get_analytics_service
"""

from typing import Annotated

from fastapi import Depends, Header

from app.core.redis_client import UpstashRedisClient, get_redis_client
from app.core.security import get_current_user_id as _get_current_user_id
from app.core.supabase_client import get_supabase_client
from app.repositories.twitter_account_repository import TwitterAccountRepository
from app.repositories.twitter_post_repository import TwitterPostRepository
from app.services.twitter_account_service import TwitterAccountService
from app.services.twitter_client import TwitterAPIClient
from app.services.twitter_oauth_service import TwitterOAuthService
from app.services.twitter_schedule_service import TwitterScheduleService
from app.services.twitter_token_service import TwitterTokenService


# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
def get_current_user_id(authorization: Annotated[str | None, Header()] = None) -> str:
    """
    Extracts and validates the Supabase-authenticated user's ID from
    the `Authorization: Bearer <token>` header sent by the Next.js
    frontend on every request to this module's endpoints.
    """
    return _get_current_user_id(authorization or "")


# ---------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------
def get_twitter_account_repository() -> TwitterAccountRepository:
    return TwitterAccountRepository(get_supabase_client())


def get_twitter_post_repository() -> TwitterPostRepository:
    return TwitterPostRepository(get_supabase_client())


# ---------------------------------------------------------------------
# Core infra
# ---------------------------------------------------------------------
def get_redis() -> UpstashRedisClient:
    return get_redis_client()


# ---------------------------------------------------------------------
# Token / OAuth services
# ---------------------------------------------------------------------
def get_token_service(
    account_repository: Annotated[TwitterAccountRepository, Depends(get_twitter_account_repository)],
) -> TwitterTokenService:
    return TwitterTokenService(account_repository)


def get_oauth_service(
    redis_client: Annotated[UpstashRedisClient, Depends(get_redis)],
    account_repository: Annotated[TwitterAccountRepository, Depends(get_twitter_account_repository)],
) -> TwitterOAuthService:
    return TwitterOAuthService(redis_client, account_repository)


def get_account_service(
    account_repository: Annotated[TwitterAccountRepository, Depends(get_twitter_account_repository)],
) -> TwitterAccountService:
    return TwitterAccountService(account_repository)


# ---------------------------------------------------------------------
# Twitter API client factory — REQUIRES a specific twitter_account_id,
# so this is built per-request inside routers/services that already
# know which connected account they're acting on, using the token
# service to guarantee a valid (auto-refreshed) access token.
# ---------------------------------------------------------------------
async def build_twitter_client(
    account_id: str,
    user_id: str,
    token_service: TwitterTokenService,
) -> TwitterAPIClient:
    """
    Not a plain Depends() target (it needs request-specific account_id),
    so routers call this explicitly. Kept here anyway so the pattern
    for "how do I get an authenticated client" lives in one place.
    """
    access_token = await token_service.get_valid_access_token(account_id, user_id)
    return TwitterAPIClient(access_token)


# ---------------------------------------------------------------------
# Feature services that don't require a pre-built Twitter client
# ---------------------------------------------------------------------
def get_schedule_service(
    post_repository: Annotated[TwitterPostRepository, Depends(get_twitter_post_repository)],
) -> TwitterScheduleService:
    return TwitterScheduleService(post_repository)
