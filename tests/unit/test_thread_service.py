"""
tests/unit/test_thread_service.py

Unit tests for TwitterThreadService — sequential ordering, reply
chaining, and rollback-on-partial-failure (Part 9's core requirements).
"""

import pytest

from app.exceptions.twitter_exceptions import ThreadPostingError, TwitterAPIError
from app.schemas.twitter_post_schema import ThreadCreateRequest, ThreadTweetItem
from app.services.twitter_thread_service import TwitterThreadService
from tests.mocks.twitter_api_mock import FakeTwitterAPIClient, mock_tweet_create_response


def _make_post_repo_mock(mock_post_repository):
    mock_post_repository.create_post.return_value = type("Post", (), {"id": "post-1"})()
    mock_post_repository.create_post_item.side_effect = [
        type("Item", (), {"id": f"item-{i}"})() for i in range(10)
    ]
    return mock_post_repository


@pytest.mark.asyncio
async def test_thread_posts_in_order_with_reply_chaining(mock_post_repository):
    _make_post_repo_mock(mock_post_repository)
    fake_client = FakeTwitterAPIClient(
        responses=[
            mock_tweet_create_response(tweet_id="1", text="First"),
            mock_tweet_create_response(tweet_id="2", text="Second"),
            mock_tweet_create_response(tweet_id="3", text="Third"),
        ]
    )
    service = TwitterThreadService(fake_client, mock_post_repository)

    request = ThreadCreateRequest(
        twitter_account_id="acc-1",
        tweets=[
            ThreadTweetItem(text="First", media_ids=[]),
            ThreadTweetItem(text="Second", media_ids=[]),
            ThreadTweetItem(text="Third", media_ids=[]),
        ],
    )

    result = await service.post_thread(user_id="u-1", request=request, username="jdoe")

    assert result.tweet_ids == ["1", "2", "3"]
    # Second call must reply to tweet 1, third call must reply to tweet 2
    assert fake_client.calls[1]["json_body"]["reply"]["in_reply_to_tweet_id"] == "1"
    assert fake_client.calls[2]["json_body"]["reply"]["in_reply_to_tweet_id"] == "2"
    # First call must NOT have a reply field
    assert "reply" not in fake_client.calls[0]["json_body"]


@pytest.mark.asyncio
async def test_thread_rollback_on_partial_failure(mock_post_repository):
    _make_post_repo_mock(mock_post_repository)

    fake_client = FakeTwitterAPIClient(
        responses=[
            mock_tweet_create_response(tweet_id="1", text="First"),
            mock_tweet_create_response(tweet_id="2", text="Second"),
        ]
    )

    call_count = {"n": 0}
    original_side_effect = fake_client.request.side_effect

    async def flaky_request(method, path, **kwargs):
        call_count["n"] += 1
        if method == "POST" and call_count["n"] == 3:
            raise TwitterAPIError("Simulated failure on third tweet")
        return await original_side_effect(method, path, **kwargs)

    fake_client.request.side_effect = flaky_request

    service = TwitterThreadService(fake_client, mock_post_repository)
    request = ThreadCreateRequest(
        twitter_account_id="acc-1",
        tweets=[
            ThreadTweetItem(text="First", media_ids=[]),
            ThreadTweetItem(text="Second", media_ids=[]),
            ThreadTweetItem(text="Third — this will fail", media_ids=[]),
        ],
    )

    with pytest.raises(ThreadPostingError) as exc_info:
        await service.post_thread(user_id="u-1", request=request, username="jdoe")

    assert exc_info.value.posted_tweet_ids == ["1", "2"]

    # Rollback should have issued DELETE calls for both posted tweets, newest first.
    delete_calls = [c for c in fake_client.calls if c["method"] == "DELETE"]
    assert [c["path"] for c in delete_calls] == ["/tweets/2", "/tweets/1"]
