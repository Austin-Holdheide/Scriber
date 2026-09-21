"""W10: speaker diarization endpoint - labels existing segments in place."""
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException

from app.services.supabase_client import admin_client
from app.services.auth import get_current_user

router = APIRouter()


def _own_done_video(video_id: str, user_id: str) -> dict:
    try:
        _uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(404, "not found")
    r = (admin_client().table("videos")
         .select("id, filename, storage_path, status")
         .eq("id", video_id).eq("user_id", user_id).limit(1).execute())
    if not r.data:
        raise HTTPException(404, "not found")
    v = r.data[0]
    if v["status"] not in ("done", "cancelled"):
        raise HTTPException(409, "video is not transcribed yet")
    return v


@router.post("/{video_id}/diarize")
def diarize(video_id: str, user_id: str = Depends(get_current_user)):
    """Queue speaker diarization for an already-transcribed video.
    Labels existing segments in place (segments.speaker), no re-transcription."""
    v = _own_done_video(video_id, user_id)

    t = (admin_client().table("transcripts")
         .select("id").eq("video_id", video_id).limit(1).execute())
    if not t.data:
        raise HTTPException(409, "no transcript for this video")

    j = (admin_client().table("jobs")
         .select("id,stage").eq("video_id", video_id)
         .order("updated_at", desc=True).limit(1).execute())
    if j.data and j.data[0]["stage"] in ("queued", "extracting", "transcribing", "diarizing", "writing", "cancel_requested"):
        raise HTTPException(409, "a job is already active for this video")

    job_id = str(_uuid.uuid4())
    admin_client().table("jobs").insert({
        "id": job_id, "video_id": video_id, "user_id": user_id,
        "stage": "queued", "progress": 0,
    }).execute()
    admin_client().table("videos").update({"status": "queued"}).eq("id", video_id).execute()

    from app.services.queue import enqueue_diarization
    enqueue_diarization(job_id=job_id, video_id=video_id, storage_path=v["storage_path"])
    return {"job_id": job_id, "queued": "diarization"}
