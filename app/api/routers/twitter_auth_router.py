"""
app/api/routers/twitter_auth_router.py

HTTP endpoints for the OAuth 2.0 login/callback flow:
  GET /twitter/login     -> returns the Twitter authorize URL
  GET /twitter/callback  -> handles Twitter's redirect, then redirects
                             the browser back to the frontend

WHY /twitter/login RETURNS JSON INSTEAD OF A 302 REDIRECT ITSELF:
The frontend calls this from a fetch/axios request (needs the
Authorization header to identify the user), not a plain browser
navigation — so we return the URL as JSON and let the FRONTEND perform
`window.location.href = authorize_url`. A raw 302 here couldn't carry
the Supabase auth header for a plain top-level navigation anyway.

WHY /twitter/callback DOES perform a redirect (not JSON):
This endpoint is hit directly by the USER'S BROWSER via Twitter's own
redirect — there is no frontend JS in the loop to parse a JSON response.
The only correct response is an HTTP redirect back into the Next.js app.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.api.deps import get_current_user_id, get_oauth_service
from app.config.settings import Settings, get_settings
from app.exceptions.twitter_exceptions import InvalidOAuthStateError, TwitterAuthError
from app.schemas.twitter_auth_schema import TwitterLoginResponse
from app.services.twitter_oauth_service import TwitterOAuthService
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/twitter", tags=["Twitter - OAuth"])


@router.get(
    "/login",
    response_model=TwitterLoginResponse,
    summary="Start Twitter OAuth 2.0 connection",
    description=(
        "Generates a Twitter OAuth 2.0 + PKCE authorization URL for the "
        "currently authenticated user. The frontend must redirect the "
        "user's browser to `authorize_url` to continue the flow."
    ),
)
async def twitter_login(
    user_id: Annotated[str, Depends(get_current_user_id)],
    oauth_service: Annotated[TwitterOAuthService, Depends(get_oauth_service)],
) -> TwitterLoginResponse:
    authorize_url = await oauth_service.build_authorize_url(user_id)
    return TwitterLoginResponse(authorize_url=authorize_url)


@router.get(
    "/callback",
    summary="Twitter OAuth 2.0 callback (redirect target)",
    description=(
        "Twitter redirects the user's browser here after authorization. "
        "This endpoint exchanges the authorization code for tokens, "
        "stores the connected account, and redirects back to the frontend."
    ),
    response_class=RedirectResponse,
)
async def twitter_callback(
    oauth_service: Annotated[TwitterOAuthService, Depends(get_oauth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    code: str = Query(..., description="Authorization code issued by Twitter."),
    state: str = Query(..., description="CSRF state token issued by /twitter/login."),
    error: str | None = Query(default=None, description="Present if the user denied authorization."),
) -> RedirectResponse:
    if error:
        logger.warning("Twitter OAuth denied by user: %s", error)
        return RedirectResponse(url=f"{settings.FRONTEND_ERROR_REDIRECT_URL}&reason={error}")

    try:
        await oauth_service.handle_callback(code=code, state=state)
    except (TwitterAuthError, InvalidOAuthStateError) as exc:
        logger.error("Twitter OAuth callback failed: %s", exc.detail)
        return RedirectResponse(url=f"{settings.FRONTEND_ERROR_REDIRECT_URL}&reason=auth_failed")

    return RedirectResponse(url=settings.FRONTEND_SUCCESS_REDIRECT_URL)
