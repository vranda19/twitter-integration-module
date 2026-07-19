"""
app/schemas/twitter_post_schema.py

Request/response contracts for posting tweets, threads, and attaching
media. Validation here (max length, max media count) catches bad
requests BEFORE we spend a Twitter API call on them — Twitter's own
errors are much less friendly and cost rate-limit quota.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

TWEET_MAX_LENGTH = 280
MAX_MEDIA_PER_TWEET = 4


class MediaUploadResponse(BaseModel):
    """Returned by POST /twitter/media/upload."""

    media_id: str = Field(..., description="Twitter media_id to attach to a tweet via media_ids.")
    media_key: Optional[str] = Field(default=None, description="Twitter media_key, used for some v2 endpoints.")
    media_type: str = Field(..., examples=["image/jpeg", "image/gif", "video/mp4"])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"media_id": "1745938201938472960", "media_key": "3_1745938201938472960", "media_type": "image/jpeg"}
            ]
        }
    }


class TweetCreateRequest(BaseModel):
    """Request body for POST /twitter/post — a single tweet."""

    twitter_account_id: str = Field(..., description="Which connected Twitter account to post from.")
    text: str = Field(..., min_length=1, max_length=TWEET_MAX_LENGTH)
    media_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_MEDIA_PER_TWEET,
        description="media_id values previously returned by /twitter/media/upload.",
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tweet text cannot be empty or whitespace only.")
        return value

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "twitter_account_id": "b3f1c2a4-1234-4a5b-9c3d-abcdef123456",
                    "text": "Excited to launch our new feature! Check it out https://example.com #buildinpublic @examplehandle",
                    "media_ids": ["1745938201938472960"],
                }
            ]
        }
    }


class TweetResponse(BaseModel):
    """Returned by POST /twitter/post."""

    tweet_id: str
    text: str
    posted_at: datetime
    url: str = Field(..., description="Direct link to the published tweet.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "tweet_id": "1815938201938472960",
                    "text": "Excited to launch our new feature!",
                    "posted_at": "2026-07-19T10:00:00Z",
                    "url": "https://twitter.com/jdoe/status/1815938201938472960",
                }
            ]
        }
    }


class ThreadTweetItem(BaseModel):
    """One tweet within a thread request."""

    text: str = Field(..., min_length=1, max_length=TWEET_MAX_LENGTH)
    media_ids: list[str] = Field(default_factory=list, max_length=MAX_MEDIA_PER_TWEET)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Thread tweet text cannot be empty or whitespace only.")
        return value


class ThreadCreateRequest(BaseModel):
    """Request body for POST /twitter/post/thread."""

    twitter_account_id: str
    tweets: list[ThreadTweetItem] = Field(..., min_length=2, description="At least 2 tweets to form a thread.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "twitter_account_id": "b3f1c2a4-1234-4a5b-9c3d-abcdef123456",
                    "tweets": [
                        {"text": "1/ Here's why clean architecture matters 🧵", "media_ids": []},
                        {"text": "2/ It separates concerns so your codebase scales with your team.", "media_ids": []},
                        {"text": "3/ That's it — build it right the first time.", "media_ids": []},
                    ],
                }
            ]
        }
    }


class ThreadTweetResult(BaseModel):
    sequence_order: int
    tweet_id: str
    text: str
    url: str


class ThreadResponse(BaseModel):
    """Returned by POST /twitter/post/thread."""

    post_id: str = Field(..., description="Internal ID of the thread record in our database.")
    tweet_ids: list[str]
    items: list[ThreadTweetResult]
    posted_at: datetime


class ScheduledPostCreateRequest(BaseModel):
    """
    Request body for POST /twitter/post/schedule.

    NOTE: this module does NOT execute scheduling (no Celery beat task
    here, per project scope). It only persists the request with
    status='scheduled' so the scheduler owner's worker can pick it up
    and call our service layer's publish functions directly.
    """

    twitter_account_id: str
    tweets: list[ThreadTweetItem] = Field(..., min_length=1)
    scheduled_time: datetime = Field(..., description="Must be a future UTC timestamp.")

    @field_validator("scheduled_time")
    @classmethod
    def must_be_future(cls, value: datetime) -> datetime:
        now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now(timezone.utc)
        if value <= now:
            raise ValueError("scheduled_time must be in the future.")
        return value


class ScheduledPostResponse(BaseModel):
    post_id: str
    status: str
    scheduled_time: datetime
    queue_metadata: dict
