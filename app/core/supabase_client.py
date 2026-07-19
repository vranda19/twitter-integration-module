"""
app/core/supabase_client.py

Supabase Python client factory, used exclusively by the repositories
in this module.

WHY THE SERVICE ROLE KEY:
This backend service acts on behalf of authenticated users but is a
trusted server-side process — it uses the Supabase SERVICE ROLE key
(bypasses Row Level Security) and enforces the `user_id` filter manually
in every repository query instead. This is standard practice for a
FastAPI backend sitting between the frontend and Supabase: the frontend
uses the anon key + user JWT (RLS-enforced) for its own direct reads,
but write-heavy, multi-step backend operations like ours use the
service role key and take on the responsibility of scoping every query
to the correct user_id themselves.

SECURITY IMPLICATION: because RLS is bypassed, every single repository
method in this module MUST filter by user_id explicitly. This is
enforced by code review convention — see repositories/*.py, where every
query includes `.eq("user_id", user_id)`.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config.settings import settings


@lru_cache
def get_supabase_client() -> Client:
    """
    Returns a cached Supabase client instance (one per process).

    Cached because client construction sets up connection pooling
    internally — recreating it per-request would be wasteful and could
    exhaust connections under load.
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
