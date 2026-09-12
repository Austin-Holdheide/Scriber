"""Video listing endpoints (JWT-authenticated)."""
from fastapi import APIRouter, Depends, HTTPException

from app.services.supabase_client import admin_client
from app.services.auth import get_current_user

router = APIRouter()

# Prefixes the worker emits for USER-FACING failures (curated, human-phrased).
# Anything else (raw tracebacks, ffmpeg dumps) stays internal.
_HUMAN_ERROR_PREFIXES = (
    "Source file is corrupt or incomplete",
    "Source file unplayable:",
    "no speech detected",
    "source missing:",
)


def _human_error(err: str | None) -> str | None:
    if not err:
        return None
    if any(err.startswith(p) for p in _HUMAN_ERROR_PREFIXES):
        return err
    return None


@router.get("")
def list_videos(user_id: str = Depends(get_current_user)):
    vids = (
        admin_client().table("videos")
        .select("*").eq("user_id", user_id)
        .order("created_at", desc=True).execute().data
    )
    if vids:
        ids = [v["id"] for v in vids]
        jobs = (
            admin_client().table("jobs")
            .select("video_id,stage,progress,error,updated_at")
            .in_("video_id", ids).order("updated_at", desc=True).execute().data
        )
        latest: dict = {}
        for j in jobs:
            if j["video_id"] not in latest:
                latest[j["video_id"]] = j
        for v in vids:
            j = latest.get(v["id"])
            if j:
                v["stage"] = j["stage"]
                v["progress"] = j["progress"]
                v["error"] = _human_error(j.get("error"))  # None unless human-readable
    return vids


@router.get("/{video_id}")
def get_video(video_id: str, user_id: str = Depends(get_current_user)):
    r = (
        admin_client().table("videos")
        .select("*").eq("id", video_id).eq("user_id", user_id)
        .limit(1).execute()
    )
    if not r.data:
        raise HTTPException(404, "not found")
    return r.data[0]
