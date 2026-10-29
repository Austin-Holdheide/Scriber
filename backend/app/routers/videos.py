"""Video upload (streaming) endpoint.

Quota enforcement happens in three places, in this order:
  1. before reading a byte   - plan lookup + rolling upload allowance   (429)
  2. while streaming         - aborts as soon as the body passes the plan's byte cap (413)
  3. after the file lands    - ffprobe duration against the plan's length cap (422)
Only a file that clears all three is stored, enqueued and metered.
"""
import uuid
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.supabase_client import admin_client
from app.services.queue import enqueue_transcription
from app.services.auth import get_current_user
from app.services.thumbs import grab_thumbnail
from app.services import quota
from app.services.probe import probe_duration_s

log = logging.getLogger("scriber.videos")
router = APIRouter()

ALLOWED_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}


@router.post("/upload")
async def upload_video(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    """Stream upload to storage; insert videos + jobs rows; enqueue transcription.
    Thumbnail is grabbed in a background thread right after the upload lands."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"unsupported file type {ext!r}")

    # 1. may this account start another transcription at all?
    plan = quota.check_transcription(user_id)

    # cheap pre-flight when the client tells us the size up front
    if file.size:
        quota.check_size(plan, file.size)

    vid = str(uuid.uuid4())
    dest_dir = Path(settings.media_root) / "videos" / user_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{vid}{ext}"

    written = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(settings.chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                # 2. stop writing the moment the plan's ceiling is crossed
                if 0 < plan.max_upload_bytes < written:
                    raise quota._too_big(plan, plan.max_upload_bytes, written)
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except OSError:
        dest.unlink(missing_ok=True)
        log.exception("storage write failed")
        raise HTTPException(500, "storage write failed")

    # 3. the length cap needs the real file
    duration_s = probe_duration_s(dest)
    try:
        quota.check_duration(plan, duration_s)
    except HTTPException:
        dest.unlink(missing_ok=True)
        log.info("rejected %s: %.1fs exceeds the %s plan cap", vid, duration_s or 0, plan.name)
        raise

    row = {
        "id": vid,
        "user_id": user_id,
        "filename": file.filename,
        "storage_path": f"videos/{user_id}/{vid}{ext}",
        "status": "queued",
        "size_bytes": dest.stat().st_size,
    }
    if duration_s:
        row["duration_s"] = round(duration_s, 3)

    job_id = str(uuid.uuid4())
    try:
        admin_client().table("videos").insert(row).execute()
        admin_client().table("jobs").insert({
            "id": job_id, "video_id": vid, "user_id": user_id, "stage": "queued", "progress": 0,
        }).execute()
    except Exception:
        dest.unlink(missing_ok=True)
        log.exception("db insert failed")
        raise HTTPException(500, "db insert failed")

    enqueue_transcription(job_id=job_id, video_id=vid, storage_path=row["storage_path"])
    # meter only once the work is genuinely accepted
    quota.record(user_id, "transcription", video_id=vid)

    # Thumbnail in a background thread - do not delay the 201 response on ffmpeg.
    def _thumb():
        try:
            grab_thumbnail(dest)
        except Exception:
            log.exception("post-upload thumbnail failed (non-fatal)")
    threading.Thread(target=_thumb, daemon=True).start()

    return JSONResponse(status_code=201, content={
        **row, "job_id": job_id, "plan": plan.name,
        "duration_s": round(duration_s, 3) if duration_s else None,
    })
