"""
app/services/twitter_schedule_service.py

Persists a "publish this later" request. This module deliberately does
NOT run Celery tasks, beat schedules, or any polling loop — per project
scope, scheduling execution belongs to another teammate. This service's
entire job is to write a correctly-shaped row that their worker can
later read (via TwitterPostRepository.list_scheduled_due) and act on by
calling TwitterPostService.post_tweet / TwitterThreadService.post_thread
directly.

`queue_metadata` is an open JSON column specifically so the scheduler
owner can attach their own fields (e.g. celery_task_id, retry_count,
queue_name) without needing a migration on OUR table — this is the
explicit contract boundary between the two modules.
"""

from app.models.twitter_post_model import PostStatus, PostType
from app.repositories.twitter_post_repository import TwitterPostRepository
from app.schemas.twitter_post_schema import ScheduledPostCreateRequest, ScheduledPostResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TwitterScheduleService:
    def __init__(self, post_repository: TwitterPostRepository) -> None:
        self._posts = post_repository

    async def create_scheduled_post(
        self, *, user_id: str, request: ScheduledPostCreateRequest
    ) -> ScheduledPostResponse:
        post_type = PostType.THREAD if len(request.tweets) > 1 else PostType.SINGLE

        post = await self._posts.create_post(
            user_id=user_id,
            twitter_account_id=request.twitter_account_id,
            post_type=post_type,
            status=PostStatus.SCHEDULED,
            scheduled_time=request.scheduled_time,
            queue_metadata={"source": "twitter_module", "item_count": len(request.tweets)},
        )

        for index, tweet in enumerate(request.tweets):
            await self._posts.create_post_item(
                post_id=post.id,
                sequence_order=index,
                text=tweet.text,
                media_ids=tweet.media_ids,
                status=PostStatus.DRAFT,
            )

        logger.info(
            "Scheduled %s post_id=%s for user_id=%s at %s",
            post_type.value, post.id, user_id, request.scheduled_time.isoformat(),
        )

        return ScheduledPostResponse(
            post_id=post.id,
            status=post.status.value,
            scheduled_time=request.scheduled_time,
            queue_metadata=post.queue_metadata,
        )
