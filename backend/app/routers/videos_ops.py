"""Re-transcribe / cancel endpoints (W16 cheap wins).

retranscribe: re-run a video through the current pipeline without re-upload.
  Doubles as retry for failed/cancelled jobs. Deletes the existing transcript
  (cascades segments) + generated artifacts, inserts a fresh jobs row, enqueues.

cancel: stop an active job.
  - Sets jobs.cancel_requested = true (a dedicated column: worker heartbeats
    rewrite `stage` every 5s and would clobber a stage-based flag).
  - If the RQ job is still queued, it is pulled so the worker never picks it up.
  - If already running, the worker sees the flag on its next heartbeat and
    converges the row to cancelled. Extraction ffmpeg is not interruptible;
    cancellation lands at the next stage/heartbeat boundary.
"""""
import uuid as _uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.services.supabase_client import admin_client
from app.services.auth import get_current_user
from app.services.queue import enqueue_transcription

router = APIRouter()

ARTIFACT_EXTS = (".srt", ".vtt", ".docx", ".txt")
ACTIVE_STAGES = ("queued", "extracting", "transcribing", "writing")


def _own_video(video_id: str, user_id: str) -> dict:
    try:
        _uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(404, "not found")
    r = (admin_client().table("videos")
         .select("id, filename, storage_path, status")
         .eq("id", video_id).eq("user_id", user_id).limit(1).execute())
    if not r.data:
        raise HTTPException(404, "not found")
    return r.data[0]


def _latest_job(video_id: str) -> dict | None:
    r = (admin_client().table("jobs")
         .select("id,stage,progress")
         .eq("video_id", video_id)
         .order("updated_at", desc=True).limit(1).execute())
    return r.data[0] if r.data else None


def _drop_transcript_artifacts(video_id: str, storage_path: str) -> int:
    """Delete transcripts row (segments cascade) + SRT/VTT/DOCX/TXT files on NFS."""
    admin_client().table("transcripts").delete().eq("video_id", video_id).execute()
    src = Path(settings.media_root) / storage_path
    removed = 0
    for ext in ARTIFACT_EXTS:
        art = src.parent / (src.stem + ext)
        if art.exists():
            try:
                art.unlink()
                removed += 1
            except OSError:
                pass
    return removed


@router.post("/{video_id}/retranscribe")
def retranscribe(video_id: str, user_id: str = Depends(get_current_user)):
    """Re-run transcription (retry for failed/cancelled too). Replaces transcript + exports."""
    v = _own_video(video_id, user_id)
    j = _latest_job(video_id)
    if j and (j["stage"] in ACTIVE_STAGES or j["stage"] == "cancel_requested"):
        raise HTTPException(409, "a job is already active for this video - cancel it first")
    removed = _drop_transcript_artifacts(video_id, v["storage_path"])

    job_id = str(_uuid.uuid4())
    admin_client().table("jobs").insert({
        "id": job_id, "video_id": video_id, "user_id": user_id, "stage": "queued", "progress": 0,
    }).execute()
    admin_client().table("videos").update({"status": "queued"}).eq("id", video_id).execute()
    enqueue_transcription(job_id=job_id, video_id=video_id, storage_path=v["storage_path"])
    return {"job_id": job_id, "artifacts_removed": removed}


@router.post("/{video_id}/cancel")
def cancel(video_id: str, user_id: str = Depends(get_current_user)):
    """Cancel the active job. Queued jobs are pulled from RQ; running ones stop at the next heartbeat."""
    v = _own_video(video_id, user_id)
    j = _latest_job(video_id)
    if not j or j["stage"] not in ACTIVE_STAGES:
        raise HTTPException(409, "no active job to cancel")

    # dedicated flag column: survives worker heartbeat writes to stage/progress
    admin_client().table("jobs").update(
        {"cancel_requested": True, "stage": "cancel_requested", "updated_at": "now()"}
    ).eq("id", j["id"]).execute()

    mode = "running_will_stop_at_heartbeat"
    try:
        from rq.job import Job
        from app.services.queue import get_queue
        q = get_queue()
        rj = Job.fetch(f"scriber-{j['id']}", connection=q.connection)
        if rj.get_status() == "queued":
            rj.cancel()
            mode = "removed_from_queue"
    except Exception:
        pass  # job already finished/vanished: the flag still converges any requeue

    if mode == "removed_from_queue":
        admin_client().table("jobs").update(
            {"stage": "cancelled", "progress": 0, "updated_at": "now()"}
        ).eq("id", j["id"]).execute()
        admin_client().table("videos").update({"status": "cancelled"}).eq("id", video_id).execute()
    return {"cancelled": video_id, "mode": mode}
