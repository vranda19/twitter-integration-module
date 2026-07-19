"""
tests/conftest.py

Shared pytest fixtures. Sets required environment variables BEFORE any
app module is imported (Settings validates on import — tests must
supply values or every test collection fails at import time).
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

# Must be set before `app.config.settings` is imported anywhere in the
# test session, since Settings() validates eagerly at import time.
os.environ.setdefault("TWITTER_CLIENT_ID", "test_client_id")
os.environ.setdefault("TWITTER_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("TWITTER_REDIRECT_URI", "http://localhost:8000/twitter/callback")
os.environ.setdefault("TWITTER_API_KEY", "test_api_key")
os.environ.setdefault("TWITTER_API_KEY_SECRET", "test_api_key_secret")
os.environ.setdefault("TWITTER_BEARER_TOKEN", "test_bearer_token")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "vZ1zJv2v8y0kQe9r6t2yqjv3n8mYyN1p6b3n8mYyN1o=")
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
# The supabase-py client validates that the key LOOKS like a JWT
# (header.payload.signature) before it will even construct a client,
# even though tests never make real network calls — the fake value
# must match that shape or client construction raises immediately.
os.environ.setdefault(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.fake_test_signature",
)
os.environ.setdefault("SUPABASE_JWT_SECRET", "test_jwt_secret_at_least_32_chars_long")
os.environ.setdefault("UPSTASH_REDIS_REST_URL", "https://test-redis.upstash.io")
os.environ.setdefault("UPSTASH_REDIS_REST_TOKEN", "test_redis_token")

from app.models.twitter_account_model import TwitterAccountModel  # noqa: E402


@pytest.fixture
def fake_account() -> TwitterAccountModel:
    """A representative connected Twitter account with a non-expired token."""
    from app.core.security import encrypt_token

    now = datetime.now(timezone.utc)
    return TwitterAccountModel(
        id="b3f1c2a4-1234-4a5b-9c3d-abcdef123456",
        user_id="u-1234",
        twitter_user_id="1489732451",
        username="jdoe",
        display_name="Jane Doe",
        profile_image_url="https://pbs.twimg.com/profile_images/xyz/avatar.jpg",
        access_token=encrypt_token("PLAINTEXT_ACCESS_TOKEN"),
        refresh_token=encrypt_token("PLAINTEXT_REFRESH_TOKEN"),
        scope="tweet.read tweet.write users.read offline.access",
        expires_at=now + timedelta(hours=2),
        is_active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def fake_expired_account(fake_account: TwitterAccountModel) -> TwitterAccountModel:
    """Same as fake_account but with an access token that is already expired."""
    from dataclasses import replace

    return replace(fake_account, expires_at=datetime.now(timezone.utc) - timedelta(minutes=10))


@pytest.fixture
def mock_account_repository():
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_post_repository():
    repo = AsyncMock()
    return repo
