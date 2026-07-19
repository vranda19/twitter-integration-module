"""
app/repositories/twitter_post_repository.py

Data-access layer for `twitter_posts` (one row per single tweet OR
thread) and `twitter_post_items` (one row per individual tweet within
a post — for a single tweet this is exactly 1 row, for a thread it's N).

See app/repositories/twitter_account_repository.py for the reasoning
behind the Repository Pattern used throughout this module.
"""

from datetime import datetime, timezone
from typing import Optional

from supabase import Client

from app.models.twitter_post_model import (
    PostStatus,
    PostType,
    TwitterPostItemModel,
    TwitterPostModel,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

POSTS_TABLE = "twitter_posts"
POST_ITEMS_TABLE = "twitter_post_items"


class TwitterPostRepository:
    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    async def create_post(
        self,
        *,
        user_id: str,
        twitter_account_id: str,
        post_type: PostType,
        status: PostStatus,
        scheduled_time: Optional[datetime] = None,
        queue_metadata: Optional[dict] = None,
    ) -> TwitterPostModel:
        payload = {
            "user_id": user_id,
            "twitter_account_id": twitter_account_id,
            "post_type": post_type.value,
            "status": status.value,
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "queue_metadata": queue_metadata or {},
        }
        response = self._db.table(POSTS_TABLE).insert(payload).execute()
        row = response.data[0]
        logger.info("Created twitter_posts row id=%s type=%s", row["id"], post_type.value)
        return TwitterPostModel.from_db_row(row)

    async def create_post_item(
        self,
        *,
        post_id: str,
        sequence_order: int,
        text: str,
        media_ids: list[str],
        status: PostStatus = PostStatus.DRAFT,
        twitter_tweet_id: Optional[str] = None,
    ) -> TwitterPostItemModel:
        payload = {
            "post_id": post_id,
            "sequence_order": sequence_order,
            "text": text,
            "media_ids": media_ids,
            "status": status.value,
            "twitter_tweet_id": twitter_tweet_id,
        }
        response = self._db.table(POST_ITEMS_TABLE).insert(payload).execute()
        return TwitterPostItemModel.from_db_row(response.data[0])

    async def update_post_item_result(
        self,
        item_id: str,
        *,
        status: PostStatus,
        twitter_tweet_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> TwitterPostItemModel:
        payload = {
            "status": status.value,
            "twitter_tweet_id": twitter_tweet_id,
            "error_message": error_message,
        }
        response = self._db.table(POST_ITEMS_TABLE).update(payload).eq("id", item_id).execute()
        return TwitterPostItemModel.from_db_row(response.data[0])

    async def update_post_status(self, post_id: str, status: PostStatus) -> TwitterPostModel:
        payload = {"status": status.value, "updated_at": datetime.now(timezone.utc).isoformat()}
        response = self._db.table(POSTS_TABLE).update(payload).eq("id", post_id).execute()
        return TwitterPostModel.from_db_row(response.data[0])

    async def get_post_with_items(
        self, post_id: str, user_id: str
    ) -> tuple[Optional[TwitterPostModel], list[TwitterPostItemModel]]:
        post_response = (
            self._db.table(POSTS_TABLE)
            .select("*")
            .eq("id", post_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not post_response.data:
            return None, []

        post = TwitterPostModel.from_db_row(post_response.data[0])

        items_response = (
            self._db.table(POST_ITEMS_TABLE)
            .select("*")
            .eq("post_id", post_id)
            .order("sequence_order")
            .execute()
        )
        items = [TwitterPostItemModel.from_db_row(row) for row in items_response.data]
        return post, items

    async def list_scheduled_due(self, before: datetime) -> list[TwitterPostModel]:
        """
        Returns posts with status='scheduled' and scheduled_time <= `before`.

        This is the read contract another teammate's Celery beat task
        will use to find work — this module only exposes the query,
        the actual periodic polling/dispatch belongs to their scheduler
        module, per project scope boundaries.
        """
        response = (
            self._db.table(POSTS_TABLE)
            .select("*")
            .eq("status", PostStatus.SCHEDULED.value)
            .lte("scheduled_time", before.isoformat())
            .execute()
        )
        return [TwitterPostModel.from_db_row(row) for row in response.data]
