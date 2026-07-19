"""
tests/integration/test_oauth_flow.py

Integration test for the OAuth login endpoint and the callback's
CSRF-state validation path — the two most security-critical endpoints
in this module.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_oauth_service
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user_id] = lambda: "u-test-1234"
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


def test_login_returns_authorize_url_with_required_params(client):
    mock_oauth_service = AsyncMock()
    mock_oauth_service.build_authorize_url.return_value = (
        "https://twitter.com/i/oauth2/authorize?response_type=code&client_id=abc"
        "&redirect_uri=http://localhost:8000/twitter/callback&scope=tweet.read"
        "&state=xyz&code_challenge=abc&code_challenge_method=S256"
    )
    app.dependency_overrides[get_oauth_service] = lambda: mock_oauth_service

    response = client.get("/twitter/login")

    assert response.status_code == 200
    body = response.json()
    assert "authorize_url" in body
    assert "code_challenge_method=S256" in body["authorize_url"]
    assert "state=" in body["authorize_url"]

    app.dependency_overrides.pop(get_oauth_service, None)


def test_callback_with_invalid_state_redirects_to_error_page(client):
    from app.exceptions.twitter_exceptions import InvalidOAuthStateError

    mock_oauth_service = AsyncMock()
    mock_oauth_service.handle_callback.side_effect = InvalidOAuthStateError("state mismatch")
    app.dependency_overrides[get_oauth_service] = lambda: mock_oauth_service

    response = client.get(
        "/twitter/callback", params={"code": "fake-code", "state": "forged-state"}, follow_redirects=False
    )

    assert response.status_code in (302, 307)
    assert "status=error" in response.headers["location"]

    app.dependency_overrides.pop(get_oauth_service, None)


def test_callback_with_user_denied_error_redirects_to_error_page(client):
    response = client.get(
        "/twitter/callback",
        params={"code": "irrelevant", "state": "irrelevant", "error": "access_denied"},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert "status=error" in response.headers["location"]
    assert "reason=access_denied" in response.headers["location"]


def test_callback_success_redirects_to_frontend_success_page(client):
    from datetime import datetime, timezone

    from app.schemas.twitter_account_schema import TwitterAccountResponse

    mock_oauth_service = AsyncMock()
    mock_oauth_service.handle_callback.return_value = TwitterAccountResponse(
        id="acc-1",
        twitter_user_id="1489732451",
        username="jdoe",
        display_name="Jane Doe",
        profile_image_url=None,
        scope="tweet.read tweet.write users.read offline.access",
        is_active=True,
        connected_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_oauth_service] = lambda: mock_oauth_service

    response = client.get(
        "/twitter/callback", params={"code": "valid-code", "state": "valid-state"}, follow_redirects=False
    )

    assert response.status_code in (302, 307)
    assert "status=success" in response.headers["location"]

    app.dependency_overrides.pop(get_oauth_service, None)
