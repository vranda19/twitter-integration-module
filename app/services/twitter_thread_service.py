"""
app/services/twitter_thread_service.py

Handles posting a multi-tweet thread as a strictly ordered chain, where
each tweet after the first is posted as a reply to the previous one
(Twitter has no native "thread" object — a thread IS just a chain of
replies from the same author, which Twitter's client renders as one).

WHY ORDER MUST BE STRICTLY SEQUENTIAL (not parallel):
Tweet N+1 needs the real tweet_id of tweet N (returned only after it's
successfully posted) to set `reply.in_reply_to_tweet_id`. This makes
thread posting inherently sequential — we cannot parallelize it, and
each step depends on the previous succeeding.

WHY ROLLBACK MATTERS:
If tweet 3 of 5 fails (network error, rate limit, Twitter 5xx), the
user now has an orphaned partial thread live on their profile — tweets
1-2 exist without their conclusion. This service attempts to DELETE the
already-posted tweets to leave a clean slate, then raises
ThreadPostingError so the user can retry the whole thread rather than
manually cleaning up Twitter.

NOTE on rollback limitations: rollback is best-effort. If the DELETE
calls themselves fail (e.g. Twitter is down), we cannot guarantee full
cleanup — the error response includes exactly which tweet_ids were
posted so the user/support can manually verify state.
"""

from datetime import datetime, timezone

from app.exceptions.twitter_exceptions import ThreadPostingError, TwitterAPIError
from app.models.twitter_post_model import PostStatus, PostType
from app.repositories.twitter_post_repository import TwitterPostRepository
from app.schemas.twitter_post_schema import ThreadCreateRequest, ThreadResponse, ThreadTweetResult
from app.services.twitter_client import TwitterAPIClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TwitterThreadService:
    def __init__(self, client: TwitterAPIClient, post_repository: TwitterPostRepository) -> None:
        self._client = client
        self._posts = post_repository

    async def post_thread(self, *, user_id: str, request: ThreadCreateRequest, username: str) -> ThreadResponse:
        post = await self._posts.create_post(
            user_id=user_id,
            twitter_account_id=request.twitter_account_id,
            post_type=PostType.THREAD,
            status=PostStatus.PUBLISHING,
        )

        # Pre-create all item rows up front (status=DRAFT) so the full
        # intended thread is visible in our DB even before any tweet
        # is actually sent — useful for debugging partial failures.
        items = []
        for index, tweet in enumerate(request.tweets):
            item = await self._posts.create_post_item(
                post_id=post.id,
                sequence_order=index,
                text=tweet.text,
                media_ids=tweet.media_ids,
                status=PostStatus.DRAFT,
            )
            items.append(item)

        posted_tweet_ids: list[str] = []
        results: list[ThreadTweetResult] = []
        previous_tweet_id: str | None = None

        try:
            for index, tweet in enumerate(request.tweets):
                body: dict = {"text": tweet.text}
                if tweet.media_ids:
                    body["media"] = {"media_ids": tweet.media_ids}
                if previous_tweet_id is not None:
                    body["reply"] = {"in_reply_to_tweet_id": previous_tweet_id}

                api_result = await self._client.request("POST", "/tweets", json_body=body)
                tweet_id = api_result["data"]["id"]
                posted_text = api_result["data"]["text"]

                await self._posts.update_post_item_result(
                    items[index].id, status=PostStatus.PUBLISHED, twitter_tweet_id=tweet_id
                )

                posted_tweet_ids.append(tweet_id)
                results.append(
                    ThreadTweetResult(
                        sequence_order=index,
                        tweet_id=tweet_id,
                        text=posted_text,
                        url=f"https://twitter.com/{username}/status/{tweet_id}",
                    )
                )
                previous_tweet_id = tweet_id

                logger.info(
                    "Posted thread item %s/%s tweet_id=%s post_id=%s",
                    index + 1, len(request.tweets), tweet_id, post.id,
                )

        except (TwitterAPIError, Exception) as exc:
            failed_index = len(posted_tweet_ids)
            await self._posts.update_post_item_result(
                items[failed_index].id, status=PostStatus.FAILED, error_message=str(exc)
            )
            logger.error(
                "Thread posting failed at item %s/%s post_id=%s — attempting rollback of %s posted tweets",
                failed_index + 1, len(request.tweets), post.id, len(posted_tweet_ids),
            )

            await self._rollback(posted_tweet_ids)
            await self._posts.update_post_status(post.id, PostStatus.FAILED)

            raise ThreadPostingError(
                f"Thread posting failed at tweet {failed_index + 1} of {len(request.tweets)}. "
                f"Successfully posted tweets were rolled back where possible.",
                posted_tweet_ids=posted_tweet_ids,
                context={"post_id": post.id},
            ) from exc

        await self._posts.update_post_status(post.id, PostStatus.PUBLISHED)

        return ThreadResponse(
            post_id=post.id,
            tweet_ids=posted_tweet_ids,
            items=results,
            posted_at=datetime.now(timezone.utc),
        )

    async def _rollback(self, tweet_ids: list[str]) -> None:
        """
        Best-effort deletion of already-posted thread tweets, in reverse
        order (delete the reply before its parent, though Twitter does
        not strictly require this ordering — done for cleanliness).
        """
        for tweet_id in reversed(tweet_ids):
            try:
                await self._client.request("DELETE", f"/tweets/{tweet_id}")
                logger.info("Rolled back (deleted) tweet_id=%s", tweet_id)
            except Exception as exc:  # noqa: BLE001 — rollback is best-effort, must not raise
                logger.error("Rollback failed to delete tweet_id=%s: %s", tweet_id, str(exc))
