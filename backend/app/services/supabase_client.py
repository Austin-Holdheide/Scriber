"""Supabase admin client (service key - SERVER ONLY, never exposed to frontend)."""
from functools import lru_cache
from supabase import create_client, Client
from app.config import settings


@lru_cache(maxsize=1)
def admin_client():
    if not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_SERVICE_KEY not set")
    return create_client(settings.supabase_url, settings.supabase_service_key)
