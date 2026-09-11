"""Global transcript search (W11) - Postgres FTS via search_segments_for_user RPC."""
from fastapi import APIRouter, Depends, HTTPException

from app.services.supabase_client import admin_client
from app.services.auth import get_current_user

router = APIRouter()


@router.get("")
def search(q: str, user_id: str = Depends(get_current_user)):
    q = q.strip()
    if not q:
        return {"query": q, "results": [], "count": 0}
    if len(q) > 200:
        raise HTTPException(422, "query too long")

    r = admin_client().rpc("search_segments_for_user", {"query": q, "user": user_id}).execute()
    return {
        "query": q,
        "results": r.data or [],
        "count": len(r.data or []),
    }
