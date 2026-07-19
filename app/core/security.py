"""
app/core/security.py

Encryption at rest for OAuth tokens, and JWT verification for
Supabase-authenticated requests.

WHY TOKENS MUST BE ENCRYPTED (not just stored as plain text in Postgres):
Even though Supabase enforces Row Level Security and the DB connection
is TLS-encrypted in transit, a leaked database backup, a misconfigured
RLS policy, or a compromised service-role key would otherwise expose
every connected user's live Twitter access + refresh tokens in plain
text. Encrypting at the application layer means a raw DB dump alone is
NOT enough to impersonate users on Twitter — the attacker also needs
TOKEN_ENCRYPTION_KEY, which lives only in the backend's env, never in
the database.

We use Fernet (symmetric, from the `cryptography` library) because:
  - it's authenticated encryption (tampering is detected, not just hidden)
  - it's simple: one key, encrypt/decrypt, no key-management infra needed
    for a single-backend-service module like this
  - it's the industry-standard recommendation for "encrypt small secrets
    at the application layer" in Python
"""

from functools import lru_cache

import jwt
from cryptography.fernet import Fernet, InvalidToken
from jwt import PyJWTError

from app.config.settings import settings
from app.exceptions.twitter_exceptions import TwitterAuthError
from app.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache
def _get_fernet() -> Fernet:
    """
    Builds the Fernet cipher once per process from TOKEN_ENCRYPTION_KEY.

    Cached because constructing a Fernet instance involves key decoding —
    cheap, but there's no reason to repeat it on every single token
    encrypt/decrypt call across a high-throughput posting service.
    """
    try:
        return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as exc:
        # Fail loudly at first use if the key is malformed — this must
        # never silently no-op and store tokens in plain text.
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is invalid. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        ) from exc


def encrypt_token(plain_text_token: str) -> str:
    """
    Encrypts a token (access_token or refresh_token) before it is
    written to the twitter_accounts table.

    Returns a url-safe base64 string, safe to store in a Postgres
    TEXT column.
    """
    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(plain_text_token.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypts a token read from the database, immediately before it is
    used to call the Twitter API.

    Raises RuntimeError on tamper/corruption detection (InvalidToken) —
    this should never happen in normal operation, and if it does, it
    indicates either data corruption or the encryption key was rotated
    without a token re-encryption migration. Either way, we must not
    silently return garbage that gets sent to Twitter as a "token".
    """
    fernet = _get_fernet()
    try:
        decrypted_bytes = fernet.decrypt(encrypted_token.encode("utf-8"))
    except InvalidToken as exc:
        logger.error("Token decryption failed — possible tampering or key mismatch")
        raise RuntimeError("Failed to decrypt stored token") from exc
    return decrypted_bytes.decode("utf-8")


def get_current_user_id(authorization_header: str) -> str:
    """
    Validates a Supabase Auth JWT (passed by the Next.js frontend as
    `Authorization: Bearer <supabase_access_token>`) and returns the
    authenticated user's UUID (the JWT `sub` claim).

    WHY THIS LIVES HERE AND NOT IN A ROUTER:
    Every protected endpoint in this module needs this exact same
    validation. Centralizing it means one file to update if Supabase
    ever changes its JWT structure or signing algorithm.

    This module does NOT own user signup/login (that's Supabase Auth,
    owned by the platform team) — it only verifies tokens issued by it.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise TwitterAuthError("Missing or malformed Authorization header")

    raw_token = authorization_header.removeprefix("Bearer ").strip()

    try:
        payload = jwt.decode(
            raw_token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except PyJWTError as exc:
        logger.warning("Rejected invalid Supabase JWT: %s", str(exc))
        raise TwitterAuthError("Invalid or expired session token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise TwitterAuthError("Session token missing subject claim")

    return user_id
