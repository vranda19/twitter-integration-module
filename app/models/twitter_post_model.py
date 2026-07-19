"""
app/models/twitter_post_model.py

Typed internal representation of rows in `twitter_posts` and
`twitter_post_items` (single tweets and thread items respectively).

WHY WE TRACK POSTS IN OUR OWN DATABASE (not just fire-and-forget to Twitter):
1. Auditability — support/debugging needs "what did we actually send
   and when" independent of Twitter's own history.
2. Scheduling handoff (Part 10) — another teammate's Celery worker reads
   rows with status='scheduled' and calls our service layer to publish
   them; this table is the contract between our module and theirs.
3. Thread rollback — if tweet 3 of 5 fails, we need to know which of
   the prior 2 succeeded to attempt cleanup.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class PostStatus(str, Enum):
    """
    Lifecycle of a post record.

    DRAFT: created but not yet queued (not used by this module directly,
           reserved for future use by another team member's editor UI).
    SCHEDULED: has a future scheduled_time; awaiting the scheduler worker.
    PUBLISHING: actively being sent to Twitter right now (prevents double-send
                if a retry mechanism overlaps with an in-flight request).
    PUBLISHED: successfully posted; twitter_post_id is populated.
    FAILED: Twitter rejected it or all retries were exhausted.
    """

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class PostType(str, Enum):
    SINGLE = "single"
    THREAD = "thread"


@dataclass(frozen=True, slots=True)
class TwitterPostModel:
    """Represents one row in `twitter_posts` — a single tweet OR the parent record of a thread."""

    id: str
    user_id: str
    twitter_account_id: str
    post_type: PostType
    status: PostStatus
    scheduled_time: Optional[datetime]
    queue_metadata: dict
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_db_row(row: dict) -> "TwitterPostModel":
        return TwitterPostModel(
            id=row["id"],
            user_id=row["user_id"],
            twitter_account_id=row["twitter_account_id"],
            post_type=PostType(row["post_type"]),
            status=PostStatus(row["status"]),
            scheduled_time=_parse_optional_datetime(row.get("scheduled_time")),
            queue_metadata=row.get("queue_metadata") or {},
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
        )


@dataclass(frozen=True, slots=True)
class TwitterPostItemModel:
    """
    Represents one row in `twitter_post_items` — a single tweet within
    a post record. For PostType.SINGLE there is exactly one item.
    For PostType.THREAD there are N items ordered by `sequence_order`.
    """

    id: str
    post_id: str
    sequence_order: int
    text: str
    media_ids: list[str]
    twitter_tweet_id: Optional[str]
    status: PostStatus
    error_message: Optional[str]
    created_at: datetime

    @staticmethod
    def from_db_row(row: dict) -> "TwitterPostItemModel":
        return TwitterPostItemModel(
            id=row["id"],
            post_id=row["post_id"],
            sequence_order=row["sequence_order"],
            text=row["text"],
            media_ids=row.get("media_ids") or [],
            twitter_tweet_id=row.get("twitter_tweet_id"),
            status=PostStatus(row["status"]),
            error_message=row.get("error_message"),
            created_at=_parse_datetime(row["created_at"]),
        )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parse_optional_datetime(value: object) -> Optional[datetime]:
    if value is None:
        return None
    return _parse_datetime(value)
