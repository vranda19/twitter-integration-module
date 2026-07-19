"""
app/services/twitter_analytics_service.py

Fetches engagement metrics for a tweet (or every tweet in a thread) and
normalizes Twitter's raw response shape into our stable contract
(TweetAnalyticsResponse), so consumers never touch Twitter's field
naming directly.

WHY NORMALIZATION MATTERS HERE SPECIFICALLY:
Twitter's `public_metrics` includes like_count/retweet_count/reply_count
/quote_count/bookmark_count reliably, but `impression_count` (and any
`non_public_metrics`) is only returned for tweets owned by the
authenticated user AND depends on API access tier. We treat impressions
as Optional[int] = None rather than 0, so the frontend can distinguish
"zero impressions" from "not available at your access tier" — collapsing
that distinction would be misleading data.
"""

from datetime import datetime, timezone

from app.exceptions.twitter_exceptions import TwitterAPIError
from app.repositories.twitter_post_repository import TwitterPostRepository
from app.schemas.twitter_analytics_schema import ThreadAnalyticsResponse, TweetAnalyticsResponse
from app.services.twitter_client import TwitterAPIClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TWEET_FIELDS = "public_metrics,non_public_metrics"


class TwitterAnalyticsService:
    def __init__(self, client: TwitterAPIClient, post_repository: TwitterPostRepository) -> None:
        self._client = client
        self._posts = post_repository

    async def get_tweet_analytics(self, tweet_id: str) -> TweetAnalyticsResponse:
        """Fetches and normalizes metrics for a single tweet by its Twitter tweet_id."""
        try:
            result = await self._client.request(
                "GET", f"/tweets/{tweet_id}", params={"tweet.fields": _TWEET_FIELDS}
            )
        except TwitterAPIError:
            logger.error("Failed to fetch analytics for tweet_id=%s", tweet_id)
            raise

        return _normalize_metrics(tweet_id, result["data"])

    async def get_thread_analytics(self, post_id: str, user_id: str) -> ThreadAnalyticsResponse:
        """
        Fetches and normalizes metrics for every tweet in a thread,
        plus a summed total across the whole thread — useful for a
        single "how did this thread perform overall" dashboard card.
        """
        post, items = await self._posts.get_post_with_items(post_id, user_id)
        if post is None:
            raise TwitterAPIError("Post not found.", context={"post_id": post_id})

        published_items = [item for item in items if item.twitter_tweet_id is not None]

        tweet_metrics = []
        for item in published_items:
            metrics = await self.get_tweet_analytics(item.twitter_tweet_id)
            tweet_metrics.append(metrics)

        totals = TweetAnalyticsResponse(
            tweet_id=post_id,
            likes=sum(m.likes for m in tweet_metrics),
            retweets=sum(m.retweets for m in tweet_metrics),
            replies=sum(m.replies for m in tweet_metrics),
            quotes=sum(m.quotes for m in tweet_metrics),
            bookmarks=sum(m.bookmarks for m in tweet_metrics),
            impressions=(
                sum(m.impressions for m in tweet_metrics if m.impressions is not None)
                if any(m.impressions is not None for m in tweet_metrics)
                else None
            ),
            fetched_at=datetime.now(timezone.utc),
        )

        return ThreadAnalyticsResponse(post_id=post_id, tweets=tweet_metrics, totals=totals)


def _normalize_metrics(tweet_id: str, raw_tweet_data: dict) -> TweetAnalyticsResponse:
    public_metrics = raw_tweet_data.get("public_metrics", {})
    non_public_metrics = raw_tweet_data.get("non_public_metrics", {})

    return TweetAnalyticsResponse(
        tweet_id=tweet_id,
        likes=public_metrics.get("like_count", 0),
        retweets=public_metrics.get("retweet_count", 0),
        replies=public_metrics.get("reply_count", 0),
        quotes=public_metrics.get("quote_count", 0),
        bookmarks=public_metrics.get("bookmark_count", 0),
        impressions=non_public_metrics.get("impression_count"),
        fetched_at=datetime.now(timezone.utc),
    )
