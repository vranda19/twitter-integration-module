"""
app/twitter_module.py

The single integration point for the rest of the team's application.

Whoever owns the top-level FastAPI app (main monorepo `app/main.py`,
NOT owned by this module) does exactly this to mount everything built
here:

    from app.twitter_module import twitter_router, register_twitter_error_handlers

    app = FastAPI()
    register_twitter_error_handlers(app)
    app.include_router(twitter_router)

Keeping this as one deliberate export surface means the rest of the
team never needs to know this module's internal folder structure —
they import exactly two things from exactly one file.
"""

from fastapi import APIRouter, FastAPI

from app.api.routers.twitter_account_router import router as twitter_account_router
from app.api.routers.twitter_analytics_router import router as twitter_analytics_router
from app.api.routers.twitter_auth_router import router as twitter_auth_router
from app.api.routers.twitter_post_router import router as twitter_post_router
from app.middleware.error_handler import register_error_handlers

twitter_router = APIRouter()
twitter_router.include_router(twitter_auth_router)
twitter_router.include_router(twitter_account_router)
twitter_router.include_router(twitter_post_router)
twitter_router.include_router(twitter_analytics_router)


def register_twitter_error_handlers(app: FastAPI) -> None:
    """Wraps the module's error handler registration under a module-scoped name for clarity at the call site."""
    register_error_handlers(app)
