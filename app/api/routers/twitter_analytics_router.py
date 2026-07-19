"""
app/api/routers/twitter_analytics_router.py

HTTP endpoints for engagement analytics:
  GET /twitter/analytics/tweet/{tweet_id}     -> single tweet metrics
  GET /twitter/analytics/thread/{post_id}     -> full thread metrics + totals

Analytics reads require a Twitter account context too (metrics are
fetched using that account's access token), so the account_id is passed
as a query parameter identifying which connection to read through.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    build_twitter_client,
    get_current_user_id,
    get_token_service,
    get_twitter_account_repository,
    get_twitter_post_repository,
)
from app.exceptions.twitter_exceptions import TwitterAccountNotFoundError
from app.repositories.twitter_account_repository import TwitterAccountRepository
from app.repositories.twitter_post_repository import TwitterPostRepository
from app.schemas.twitter_analytics_schema import ThreadAnalyticsResponse, TweetAnalyticsResponse
from app.services.twitter_analytics_service import TwitterAnalyticsService
from app.services.twitter_token_service import TwitterTokenService

router = APIRouter(prefix="/twitter/analytics", tags=["Twitter - Analytics"])


@router.get(
    "/tweet/{tweet_id}",
    response_model=TweetAnalyticsResponse,
    summary="Get analytics for a single tweet",
    description="Returns normalized likes, retweets, replies, quotes, bookmarks, and impressions (if available).",
)
async def get_tweet_analytics(
    tweet_id: str,
    twitter_account_id: Annotated[str, Query(..., description="Which connected account to read metrics through.")],
    user_id: Annotated[str, Depends(get_current_user_id)],
    account_repository: Annotated[TwitterAccountRepository, Depends(get_twitter_account_repository)],
    post_repository: Annotated[TwitterPostRepository, Depends(get_twitter_post_repository)],
    token_service: Annotated[TwitterTokenService, Depends(get_token_service)],
) -> TweetAnalyticsResponse:
    account = await account_repository.get_by_id(twitter_account_id, user_id)
    if account is None or not account.is_active:
        raise TwitterAccountNotFoundError("Twitter account not found or has been disconnected.")

    client = await build_twitter_client(twitter_account_id, user_id, token_service)
    analytics_service = TwitterAnalyticsService(client, post_repository)
    return await analytics_service.get_tweet_analytics(tweet_id)


@router.get(
    "/thread/{post_id}",
    response_model=ThreadAnalyticsResponse,
    summary="Get analytics for an entire thread",
    description="Returns normalized metrics for every tweet in the thread plus summed totals.",
)
async def get_thread_analytics(
    post_id: str,
    twitter_account_id: Annotated[str, Query(..., description="Which connected account to read metrics through.")],
    user_id: Annotated[str, Depends(get_current_user_id)],
    account_repository: Annotated[TwitterAccountRepository, Depends(get_twitter_account_repository)],
    post_repository: Annotated[TwitterPostRepository, Depends(get_twitter_post_repository)],
    token_service: Annotated[TwitterTokenService, Depends(get_token_service)],
) -> ThreadAnalyticsResponse:
    account = await account_repository.get_by_id(twitter_account_id, user_id)
    if account is None or not account.is_active:
        raise TwitterAccountNotFoundError("Twitter account not found or has been disconnected.")

    client = await build_twitter_client(twitter_account_id, user_id, token_service)
    analytics_service = TwitterAnalyticsService(client, post_repository)
    return await analytics_service.get_thread_analytics(post_id, user_id)
