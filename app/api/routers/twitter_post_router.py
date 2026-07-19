"""
app/api/routers/twitter_post_router.py

HTTP endpoints for content publishing:
  POST /twitter/media/upload  -> upload image/gif/video, get a media_id
  POST /twitter/post          -> post a single tweet
  POST /twitter/post/thread   -> post a multi-tweet thread
  POST /twitter/post/schedule -> persist a post for later publishing
                                  (execution owned by another module)

Every endpoint here first resolves the target twitter_account_id into
a valid, auto-refreshed access token via TwitterTokenService, then
builds a per-request TwitterAPIClient — this is the pattern documented
in app/api/deps.py.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import (
    build_twitter_client,
    get_current_user_id,
    get_schedule_service,
    get_token_service,
    get_twitter_account_repository,
    get_twitter_post_repository,
)
from app.exceptions.twitter_exceptions import TwitterAccountNotFoundError
from app.repositories.twitter_account_repository import TwitterAccountRepository
from app.repositories.twitter_post_repository import TwitterPostRepository
from app.schemas.twitter_post_schema import (
    MediaUploadResponse,
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ThreadCreateRequest,
    ThreadResponse,
    TweetCreateRequest,
    TweetResponse,
)
from app.services.twitter_media_service import TwitterMediaService
from app.services.twitter_post_service import TwitterPostService
from app.services.twitter_schedule_service import TwitterScheduleService
from app.services.twitter_thread_service import TwitterThreadService
from app.services.twitter_token_service import TwitterTokenService

router = APIRouter(prefix="/twitter", tags=["Twitter - Publishing"])


async def _resolve_account_and_client(
    account_id: str,
    user_id: str,
    account_repository: TwitterAccountRepository,
    token_service: TwitterTokenService,
):
    """
    Shared helper: verifies the account belongs to the user and builds
    an authenticated TwitterAPIClient for it. Raises
    TwitterAccountNotFoundError if the account doesn't exist or isn't
    the caller's — never leaks existence of other users' accounts.
    """
    account = await account_repository.get_by_id(account_id, user_id)
    if account is None or not account.is_active:
        raise TwitterAccountNotFoundError("Twitter account not found or has been disconnected.")

    client = await build_twitter_client(account_id, user_id, token_service)
    return account, client


@router.post(
    "/media/upload",
    response_model=MediaUploadResponse,
    summary="Upload media (image, GIF, or video)",
    description="Uploads a media file to Twitter and returns a media_id to attach to a tweet or thread item.",
)
async def upload_media(
    user_id: Annotated[str, Depends(get_current_user_id)],
    account_repository: Annotated[TwitterAccountRepository, Depends(get_twitter_account_repository)],
    token_service: Annotated[TwitterTokenService, Depends(get_token_service)],
    twitter_account_id: Annotated[str, Form(..., description="Which connected account to upload as.")],
    file: Annotated[UploadFile, File(..., description="The image, GIF, or video file to upload.")],
) -> MediaUploadResponse:
    _, client = await _resolve_account_and_client(twitter_account_id, user_id, account_repository, token_service)
    media_service = TwitterMediaService(client)

    file_bytes = await file.read()
    content_type = file.content_type or "application/octet-stream"

    return await media_service.upload_media(file_bytes=file_bytes, content_type=content_type)


@router.post(
    "/post",
    response_model=TweetResponse,
    summary="Post a single tweet",
    description="Posts a tweet with text and optional media (links/hashtags/mentions are plain text substrings).",
)
async def post_tweet(
    request: TweetCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    account_repository: Annotated[TwitterAccountRepository, Depends(get_twitter_account_repository)],
    post_repository: Annotated[TwitterPostRepository, Depends(get_twitter_post_repository)],
    token_service: Annotated[TwitterTokenService, Depends(get_token_service)],
) -> TweetResponse:
    account, client = await _resolve_account_and_client(
        request.twitter_account_id, user_id, account_repository, token_service
    )
    post_service = TwitterPostService(client, post_repository)
    return await post_service.post_tweet(user_id=user_id, request=request, username=account.username)


@router.post(
    "/post/thread",
    response_model=ThreadResponse,
    summary="Post a multi-tweet thread",
    description="Publishes an ordered list of tweets as a single reply-chain thread. Rolls back on partial failure.",
)
async def post_thread(
    request: ThreadCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    account_repository: Annotated[TwitterAccountRepository, Depends(get_twitter_account_repository)],
    post_repository: Annotated[TwitterPostRepository, Depends(get_twitter_post_repository)],
    token_service: Annotated[TwitterTokenService, Depends(get_token_service)],
) -> ThreadResponse:
    account, client = await _resolve_account_and_client(
        request.twitter_account_id, user_id, account_repository, token_service
    )
    thread_service = TwitterThreadService(client, post_repository)
    return await thread_service.post_thread(user_id=user_id, request=request, username=account.username)


@router.post(
    "/post/schedule",
    response_model=ScheduledPostResponse,
    summary="Schedule a post for later publishing",
    description=(
        "Persists a single tweet or thread with a future scheduled_time. "
        "This endpoint does NOT publish it — a separate scheduler worker "
        "(owned by another module) reads scheduled, due posts and calls "
        "this module's publishing services directly."
    ),
)
async def schedule_post(
    request: ScheduledPostCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    schedule_service: Annotated[TwitterScheduleService, Depends(get_schedule_service)],
) -> ScheduledPostResponse:
    return await schedule_service.create_scheduled_post(user_id=user_id, request=request)
