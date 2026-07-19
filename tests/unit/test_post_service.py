"""
tests/unit/test_post_service.py

Unit tests for TwitterPostService — single tweet posting, using the
FakeTwitterAPIClient so no real network call is made.
"""

import pytest

from app.schemas.twitter_post_schema import TweetCreateRequest
from app.services.twitter_post_service import TwitterPostService
from tests.mocks.twitter_api_mock import FakeTwitterAPIClient, mock_tweet_create_response


@pytest.mark.asyncio
async def test_post_tweet_success(mock_post_repository):
    fake_client = FakeTwitterAPIClient(responses=[mock_tweet_create_response(tweet_id="111", text="Hello!")])

    fake_post_row = type("Post", (), {"id": "post-1"})()
    fake_item_row = type("Item", (), {"id": "item-1"})()
    mock_post_repository.create_post.return_value = fake_post_row
    mock_post_repository.create_post_item.return_value = fake_item_row

    service = TwitterPostService(fake_client, mock_post_repository)
    request = TweetCreateRequest(twitter_account_id="acc-1", text="Hello!", media_ids=[])

    result = await service.post_tweet(user_id="u-1", request=request, username="jdoe")

    assert result.tweet_id == "111"
    assert result.text == "Hello!"
    assert result.url == "https://twitter.com/jdoe/status/111"
    mock_post_repository.update_post_item_result.assert_called_once()
    mock_post_repository.update_post_status.assert_called_once()


@pytest.mark.asyncio
async def test_post_tweet_with_media_includes_media_field(mock_post_repository):
    fake_client = FakeTwitterAPIClient(responses=[mock_tweet_create_response()])
    mock_post_repository.create_post.return_value = type("Post", (), {"id": "post-1"})()
    mock_post_repository.create_post_item.return_value = type("Item", (), {"id": "item-1"})()

    service = TwitterPostService(fake_client, mock_post_repository)
    request = TweetCreateRequest(twitter_account_id="acc-1", text="Check this out", media_ids=["media-123"])

    await service.post_tweet(user_id="u-1", request=request, username="jdoe")

    sent_body = fake_client.calls[0]["json_body"]
    assert sent_body["media"]["media_ids"] == ["media-123"]


@pytest.mark.asyncio
async def test_post_tweet_records_failure_on_api_error(mock_post_repository):
    from app.exceptions.twitter_exceptions import TwitterAPIError

    fake_client = FakeTwitterAPIClient()
    fake_client.request.side_effect = TwitterAPIError("boom")

    mock_post_repository.create_post.return_value = type("Post", (), {"id": "post-1"})()
    mock_post_repository.create_post_item.return_value = type("Item", (), {"id": "item-1"})()

    service = TwitterPostService(fake_client, mock_post_repository)
    request = TweetCreateRequest(twitter_account_id="acc-1", text="This will fail", media_ids=[])

    with pytest.raises(TwitterAPIError):
        await service.post_tweet(user_id="u-1", request=request, username="jdoe")

    mock_post_repository.update_post_item_result.assert_called_once()
    _, kwargs = mock_post_repository.update_post_item_result.call_args
    assert kwargs["status"].value == "failed"
