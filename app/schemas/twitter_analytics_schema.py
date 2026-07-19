"""
app/schemas/twitter_analytics_schema.py

Response contract for GET /twitter/analytics/{tweet_id}.

WHY "NORMALIZED": Twitter's raw API response nests metrics under
`public_metrics` / `non_public_metrics` / `organic_metrics` inconsistently
depending on auth level and endpoint version, and field availability
varies by API access tier. Consumers of THIS module (the Next.js frontend,
or a future analytics-aggregation service combining LinkedIn/Meta/Twitter
stats) should never need to know Twitter's specific response shape.
This schema is the single normalized contract they depend on.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TweetAnalyticsResponse(BaseModel):
    """Normalized engagement metrics for a single tweet."""

    tweet_id: str
    likes: int = Field(..., ge=0)
    retweets: int = Field(..., ge=0)
    replies: int = Field(..., ge=0)
    quotes: int = Field(..., ge=0)
    bookmarks: int = Field(..., ge=0)
    impressions: Optional[int] = Field(
        default=None,
        description="Null if not available at the caller's Twitter API access tier.",
    )
    fetched_at: datetime

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "tweet_id": "1815938201938472960",
                    "likes": 142,
                    "retweets": 18,
                    "replies": 7,
                    "quotes": 3,
                    "bookmarks": 26,
                    "impressions": 5230,
                    "fetched_at": "2026-07-19T12:00:00Z",
                }
            ]
        }
    }


class ThreadAnalyticsResponse(BaseModel):
    """Normalized engagement metrics for every tweet in a thread, plus aggregated totals."""

    post_id: str
    tweets: list[TweetAnalyticsResponse]
    totals: TweetAnalyticsResponse = Field(..., description="Sum of all metrics across the thread.")
