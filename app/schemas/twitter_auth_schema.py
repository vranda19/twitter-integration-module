"""
app/schemas/twitter_auth_schema.py

Request/response contracts for the OAuth login and callback endpoints.

These are intentionally minimal — the OAuth callback endpoint redirects
the browser back to the frontend rather than returning JSON, so the
schemas here mostly describe the /twitter/login response (the
authorize URL the frontend must redirect the user's browser to).
"""

from pydantic import BaseModel, Field


class TwitterLoginResponse(BaseModel):
    """Returned by GET /twitter/login — the frontend redirects the browser to `authorize_url`."""

    authorize_url: str = Field(
        ...,
        description="Full Twitter OAuth 2.0 authorization URL the user's browser must be redirected to.",
        examples=[
            "https://twitter.com/i/oauth2/authorize?response_type=code&client_id=abc123"
            "&redirect_uri=https%3A%2F%2Fapi.example.com%2Ftwitter%2Fcallback"
            "&scope=tweet.read+tweet.write+users.read+offline.access"
            "&state=xY7...&code_challenge=Q2n...&code_challenge_method=S256"
        ],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "authorize_url": "https://twitter.com/i/oauth2/authorize?response_type=code&client_id=abc123&redirect_uri=https%3A%2F%2Fapi.example.com%2Ftwitter%2Fcallback&scope=tweet.read+tweet.write+users.read+offline.access&state=xY7abc&code_challenge=Q2nZ9&code_challenge_method=S256"
                }
            ]
        }
    }


class TwitterCallbackQuery(BaseModel):
    """
    Query parameters Twitter appends to our redirect_uri after user
    authorization. FastAPI binds these automatically from the URL —
    this schema documents the contract for Swagger and for manual testing.
    """

    code: str = Field(..., description="Authorization code issued by Twitter, exchanged for tokens.")
    state: str = Field(..., description="Must match the state we issued at /twitter/login (CSRF check).")
    error: str | None = Field(
        default=None,
        description="Present if the user denied authorization or Twitter rejected the request.",
    )
