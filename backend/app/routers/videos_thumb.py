"""Thumbnail serving (W16 cheap win).

Thumbs are JPEG frames grabbed at upload / transcription time. They are served with
the same dual auth as /download (Bearer header OR signed ?mt=&mu= query params)
because <img> tags cannot send Authorization headers.
"""""
import uuid as _uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.config import settings
from app.services.supabase_client import admin_client
from app.services.auth import get_current_user
from app.services.media_token import issue as issue_media_token, verify as verify_media_token
from app.services.thumbs import thumb_path_for

router = APIRouter()


def _load_video(video_id: str, user_id: str) -> dict:
    r = (admin_client().table("videos")
         .select("id, storage_path, user_id")
         .eq("id", video_id).eq("user_id", user_id).limit(1).execute())
    if not r.data:
        raise HTTPException(404, "not found")
    return r.data[0]


@router.post("/thumb-tokens")
def thumb_tokens(user_id: str = Depends(get_current_user)):
    """Batch: signed tokens for every owned video that has a thumbnail on disk.
    One request per library view instead of one per <img>."""
    vids = (admin_client().table("videos")
            .select("id, storage_path").eq("user_id", user_id).execute().data)
    tokens = {}
    for v in vids:
        tp = thumb_path_for(v["storage_path"])
        if tp and tp.exists():
            tokens[v["id"]] = issue_media_token(v["id"], user_id)
    return {"tokens": tokens, "ttl": 600}


@router.get("/{video_id}/thumbnail")
def thumbnail(video_id: str, request: Request):
    """Dual auth (Bearer header OR ?mt=&mu= signed token) -> JPEG frame."""
    mt = request.query_params.get("mt", "")
    mu = request.query_params.get("mu", "")
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        user_id = get_current_user(request)
    elif mt and mu:
        if not verify_media_token(video_id, mu, mt):
            raise HTTPException(401, "invalid or expired media token")
        user_id = mu
    else:
        raise HTTPException(401, "missing auth")

    try:
        _uuid.UUID(video_id)
        _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(404, "not found")

    v = _load_video(video_id, user_id)
    tp = thumb_path_for(v["storage_path"])
    if not tp or not tp.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(tp, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})
