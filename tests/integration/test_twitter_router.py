"""
tests/integration/test_twitter_router.py

Integration tests using FastAPI's TestClient — exercises real routing,
dependency injection, and request/response validation end-to-end,
while overriding only the outermost dependencies (auth, repositories,
Twitter client) so no real network or database calls happen.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_current_user_id,
    get_twitter_account_repository,
)
from app.main import app
from app.models.twitter_account_model import TwitterAccountModel


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user_id] = lambda: "u-test-1234"
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


def _sample_account() -> TwitterAccountModel:
    from app.core.security import encrypt_token

    now = datetime.now(timezone.utc)
    return TwitterAccountModel(
        id="acc-1",
        user_id="u-test-1234",
        twitter_user_id="1489732451",
        username="jdoe",
        display_name="Jane Doe",
        profile_image_url=None,
        access_token=encrypt_token("PLAINTEXT_TOKEN"),
        refresh_token=encrypt_token("PLAINTEXT_REFRESH"),
        scope="tweet.read tweet.write users.read offline.access",
        expires_at=now + timedelta(hours=1),
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_list_accounts_returns_connected_accounts(client):
    mock_repo = AsyncMock()
    mock_repo.list_by_user.return_value = [_sample_account()]
    app.dependency_overrides[get_twitter_account_repository] = lambda: mock_repo

    response = client.get("/twitter/accounts")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["accounts"][0]["username"] == "jdoe"
    # SECURITY: ensure tokens never appear in the response
    assert "access_token" not in body["accounts"][0]
    assert "refresh_token" not in body["accounts"][0]

    app.dependency_overrides.pop(get_twitter_account_repository, None)


def test_disconnect_account_not_found_returns_404(client):
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    app.dependency_overrides[get_twitter_account_repository] = lambda: mock_repo

    response = client.delete("/twitter/accounts/nonexistent-id")

    assert response.status_code == 404
    assert response.json()["error_code"] == "TWITTER_ACCOUNT_NOT_FOUND"

    app.dependency_overrides.pop(get_twitter_account_repository, None)


def test_post_tweet_validation_rejects_empty_text(client):
    response = client.post(
        "/twitter/post",
        json={"twitter_account_id": "acc-1", "text": "", "media_ids": []},
    )
    assert response.status_code == 422


def test_post_thread_requires_at_least_two_tweets(client):
    response = client.post(
        "/twitter/post/thread",
        json={"twitter_account_id": "acc-1", "tweets": [{"text": "Only one", "media_ids": []}]},
    )
    assert response.status_code == 422


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
