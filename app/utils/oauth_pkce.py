"""
app/utils/oauth_pkce.py

Generates the `state` (CSRF protection) and PKCE `code_verifier` /
`code_challenge` pair required by Twitter's OAuth 2.0 Authorization
Code flow.

WHY PKCE (Proof Key for Code Exchange) IS MANDATORY FOR TWITTER:
Twitter's OAuth 2.0 requires PKCE even for confidential (server-side)
clients. PKCE prevents an authorization-code-interception attack: even
if an attacker somehow captured the `code` mid-flow, they cannot
exchange it for a token without the original `code_verifier`, which
never leaves our backend.

WHY `state` IS SEPARATE FROM PKCE:
`state` defends against CSRF — it proves the callback request actually
originated from an authorization request WE initiated for THIS user's
browser session, not an attacker tricking a logged-in user into linking
the attacker's Twitter account. PKCE defends against code interception.
They solve different problems and both are required.
"""

import base64
import hashlib
import secrets


def generate_csrf_state() -> str:
    """
    Generates a cryptographically random, URL-safe string used as the
    OAuth `state` parameter.

    32 bytes of entropy (secrets.token_urlsafe default) is well beyond
    what's brute-forceable within the 10-minute TTL this value lives for.
    """
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> tuple[str, str]:
    """
    Returns (code_verifier, code_challenge).

    code_verifier: a random string, kept SERVER-SIDE ONLY (stored in
    Redis alongside `state`, never sent to the browser or to Twitter
    until the final token exchange).

    code_challenge: SHA-256 hash of code_verifier, base64url-encoded
    with padding stripped (per RFC 7636). This IS sent to Twitter in
    the initial /authorize redirect. Twitter stores it, and later
    verifies that the code_verifier we send during token exchange
    hashes to the same value — proving the token exchange request
    comes from whoever initiated the authorize request.
    """
    code_verifier = secrets.token_urlsafe(64)

    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

    return code_verifier, code_challenge
