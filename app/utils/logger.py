"""
app/utils/logger.py

Centralized logger factory for the Twitter module.

WHY THIS EXISTS:
Every service/router in this module calls `get_logger(__name__)` instead
of `logging.getLogger(__name__)` directly. That gives us one place to:
  - enforce a consistent structured log format across the whole module
  - guarantee we NEVER accidentally log secrets (tokens, client secret)
  - swap output format (e.g. to JSON for production log aggregation)
    without touching every file that logs something

Twitter API responses and OAuth payloads often contain sensitive fields.
`safe_log_context()` is the mandatory sanitizer any service must run
request/response payloads through before passing them into `extra=`.
"""

import logging
import sys
from typing import Any

from app.config.settings import settings

_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "code_verifier",
    "code_challenge",
    "authorization",
    "bearer_token",
    "api_key_secret",
    "token_encryption_key",
    "supabase_service_role_key",
    "supabase_jwt_secret",
}


def _configure_root_handler() -> None:
    """
    Attaches a single StreamHandler to the root logger exactly once.

    Guards against duplicate log lines, which happens if this module
    gets imported multiple times (common in test collection / reload
    scenarios) and each import naively calls addHandler again.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())


def get_logger(name: str) -> logging.Logger:
    """
    Returns a module-scoped logger, e.g. get_logger(__name__) inside
    app/services/twitter_oauth_service.py yields a logger named
    'app.services.twitter_oauth_service' — makes log lines traceable
    to their source file at a glance.
    """
    _configure_root_handler()
    return logging.getLogger(name)


def safe_log_context(data: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively redacts sensitive keys from a dict before it's logged.

    WHY: services frequently want to log "here is the payload we sent
    to Twitter" for debugging. Without this, an access_token or
    client_secret could end up in plaintext in log aggregation systems
    (Datadog, CloudWatch, etc.), which is a severe security incident.

    Usage:
        logger.info("Exchanging OAuth code", extra=safe_log_context(payload))
    """
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            redacted[key] = "***REDACTED***"
        elif isinstance(value, dict):
            redacted[key] = safe_log_context(value)
        else:
            redacted[key] = value
    return redacted
