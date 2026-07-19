"""
app/services/twitter_post_service.py

Handles posting a single tweet. Links, hashtags, and @mentions are NOT
separate API parameters in Twitter's v2 API — they're plain substrings
of `text` that Twitter auto-parses/renders on their side (a hashtag is
just "#word" in the text; a mention is "@handle" in the text; a link is
a URL substring that Twitter auto-shortens for display). This service's
job is therefore to validate and send `text` + `media_ids` correctly,
and to record the outcome in our own database for audit/history.
"""

from datetime import datetime, timezone

from app.exceptions.twitter_exceptions import TwitterAPIError, TwitterValidationError
from app.models.twitter_post_model import PostStatus, PostType
from app.repositories.twitter_post_repository import TwitterPostRepository
from app.schemas.twitter_post_schema import TweetCreateRequest, TweetResponse
from app.services.twitter_client import TwitterAPIClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TwitterPostService:
    def __init__(self, client: TwitterAPIClient, post_repository: TwitterPostRepository) -> None:
        self._client = client
        self._posts = post_repository

    async def post_tweet(self, *, user_id: str, request: TweetCreateRequest, username: str) -> TweetResponse:
        """
        Posts a single tweet and records it in twitter_posts /
        twitter_post_items regardless of outcome, so there is always an
        audit trail of what was attempted.
        """
        post = await self._posts.create_post(
            user_id=user_id,
            twitter_account_id=request.twitter_account_id,
            post_type=PostType.SINGLE,
            status=PostStatus.PUBLISHING,
        )
        item = await self._posts.create_post_item(
            post_id=post.id,
            sequence_order=0,
            text=request.text,
            media_ids=request.media_ids,
            status=PostStatus.PUBLISHING,
        )

        body: dict = {"text": request.text}
        if request.media_ids:
            body["media"] = {"media_ids": request.media_ids}

        try:
            result = await self._client.request("POST", "/tweets", json_body=body)
        except (TwitterAPIError, Exception) as exc:
            await self._posts.update_post_item_result(
                item.id, status=PostStatus.FAILED, error_message=str(exc)
            )
            await self._posts.update_post_status(post.id, PostStatus.FAILED)
            logger.error("Failed to post tweet for user_id=%s: %s", user_id, str(exc))
            raise

        tweet_id = result["data"]["id"]
        posted_text = result["data"]["text"]

        await self._posts.update_post_item_result(item.id, status=PostStatus.PUBLISHED, twitter_tweet_id=tweet_id)
        await self._posts.update_post_status(post.id, PostStatus.PUBLISHED)

        logger.info("Posted tweet id=%s for user_id=%s account_id=%s", tweet_id, user_id, request.twitter_account_id)

        return TweetResponse(
            tweet_id=tweet_id,
            text=posted_text,
            posted_at=datetime.now(timezone.utc),
            url=f"https://twitter.com/{username}/status/{tweet_id}",
        )


def validate_media_belongs_to_request(media_ids: list[str], max_allowed: int = 4) -> None:
    """
    Shared validation used by both single-tweet and thread posting —
    Twitter allows a maximum of 4 media items per individual tweet.
    """
    if len(media_ids) > max_allowed:
        raise TwitterValidationError(f"A single tweet cannot have more than {max_allowed} media attachments.")
