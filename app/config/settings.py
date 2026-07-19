"""
app/config/settings.py

Centralized, validated configuration for the X (Twitter) Integration module.

Every other file that needs an environment variable imports `settings`
from here instead of calling os.getenv() directly. This guarantees:

  1. Fail-fast startup: if a required variable is missing/malformed,
     the app crashes on import, not mid-request in production.
  2. One authoritative list of every config value this module depends on.
  3. Easy test overrides (monkeypatch the `settings` singleton instead
     of mutating process environment variables).

This module owns ONLY Twitter-related and module-local settings
(encryption key, Redis URL, Supabase creds needed for this module).
It does not own settings for other teammates' modules (LinkedIn, Meta,
AI Writer, Scheduler) — `extra="ignore"` lets it coexist safely in a
shared .env file in the monorepo.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ---------------------------------------------------------------
    # Twitter OAuth 2.0 (Authorization Code + PKCE)
    # ---------------------------------------------------------------
    TWITTER_CLIENT_ID: str
    TWITTER_CLIENT_SECRET: str
    TWITTER_REDIRECT_URI: str
    TWITTER_OAUTH_SCOPES: str = "tweet.read tweet.write users.read offline.access"

    TWITTER_AUTHORIZE_URL: str = "https://twitter.com/i/oauth2/authorize"
    TWITTER_TOKEN_URL: str = "https://api.twitter.com/2/oauth2/token"
    TWITTER_REVOKE_URL: str = "https://api.twitter.com/2/oauth2/revoke"

    # ---------------------------------------------------------------
    # Twitter OAuth 1.0a (legacy — required by some media-upload paths)
    # ---------------------------------------------------------------
    TWITTER_API_KEY: str
    TWITTER_API_KEY_SECRET: str

    # ---------------------------------------------------------------
    # Twitter app-only auth
    # ---------------------------------------------------------------
    TWITTER_BEARER_TOKEN: str

    # ---------------------------------------------------------------
    # Twitter API base URLs
    # ---------------------------------------------------------------
    TWITTER_API_BASE_URL: str = "https://api.twitter.com/2"
    TWITTER_UPLOAD_BASE_URL: str = "https://upload.twitter.com/1.1"

    # ---------------------------------------------------------------
    # Token encryption (Fernet symmetric key — 32 url-safe base64 bytes)
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # ---------------------------------------------------------------
    TOKEN_ENCRYPTION_KEY: str

    # ---------------------------------------------------------------
    # Supabase (this module only needs the service-role client to
    # read/write twitter_accounts / twitter_posts, and the JWT secret
    # to validate the logged-in user attached by Supabase Auth)
    # ---------------------------------------------------------------
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str

    # ---------------------------------------------------------------
    # Upstash Redis (used for short-lived OAuth state/PKCE storage)
    # ---------------------------------------------------------------
    UPSTASH_REDIS_REST_URL: str
    UPSTASH_REDIS_REST_TOKEN: str

    # ---------------------------------------------------------------
    # General module behavior
    # ---------------------------------------------------------------
    OAUTH_STATE_TTL_SECONDS: int = 600  # 10 minutes to complete OAuth
    HTTP_TIMEOUT_SECONDS: float = 15.0
    HTTP_MAX_RETRIES: int = 3
    FRONTEND_SUCCESS_REDIRECT_URL: str = "http://localhost:3000/settings/integrations?status=success"
    FRONTEND_ERROR_REDIRECT_URL: str = "http://localhost:3000/settings/integrations?status=error"

    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = Field(default="development")  # development | staging | production

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor.

    lru_cache ensures Settings() is constructed exactly once per process
    (parsing/validating env vars is not free — no reason to repeat it on
    every dependency-injected request). FastAPI routes pull this via
    Depends(get_settings) so it can be overridden in tests with
    app.dependency_overrides[get_settings].
    """
    return Settings()


# Module-level singleton for non-DI contexts (e.g. Celery tasks, scripts)
settings = get_settings()
