"""Segment editing endpoints (W9 inline editor)."""
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.services.supabase_client import admin_client
from app.services.auth import get_current_user

router = APIRouter()


class SegmentUpdate(BaseModel):
    text: str | None = None
    speaker: str | None = None

    @field_validator("text", "speaker")
    @classmethod
    def not_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("cannot be blank")
        return v.strip() if v else v


def _segment_owned(segment_id: int, user_id: str) -> dict:
    """Load segment; verify ownership through transcript->video->user chain."""
    seg = (
        admin_client().table("segments")
        .select("id,transcript_id,text,speaker,start_ms")
        .eq("id", segment_id).limit(1).execute().data
    )
    if not seg:
        raise HTTPException(404, "segment not found")
    vid = (
        admin_client().table("transcripts")
        .select("video_id").eq("id", seg[0]["transcript_id"]).limit(1).execute().data
    )
    if not vid:
        raise HTTPException(404, "segment not found")
    own = (
        admin_client().table("videos")
        .select("id").eq("id", vid[0]["video_id"]).eq("user_id", user_id).limit(1).execute().data
    )
    if not own:
        raise HTTPException(404, "segment not found")  # 404, not 403: don't leak existence
    return seg[0]


@router.patch("/{segment_id}")
def update_segment(segment_id: int, body: SegmentUpdate, user_id: str = Depends(get_current_user)):
    if body.text is None and body.speaker is None:
        raise HTTPException(422, "nothing to update")
    seg = _segment_owned(segment_id, user_id)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    r = admin_client().table("segments").update(patch).eq("id", segment_id).execute()
    return r.data[0]
