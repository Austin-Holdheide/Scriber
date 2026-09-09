"""Video listing endpoints."""
from fastapi import APIRouter, HTTPException

from app.services.supabase_client import admin_client

router = APIRouter()


@router.get("")
def list_videos(user_id: str):
    r = admin_client().table("videos").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return r.data


@router.get("/{video_id}")
def get_video(video_id: str, user_id: str):
    import uuid as _uuid
    try:
        _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(403, "invalid user id")
    r = (
        admin_client()
        .table("videos")
        .select("*")
        .eq("id", video_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "not found")
    return r.data[0]
