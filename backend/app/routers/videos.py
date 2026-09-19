"""Video upload (streaming) endpoint."""
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

log = logging.getLogger("scriber.videos")
router = APIRouter()

ALLOWED_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}


@router.post("/upload")
async def upload_video(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    """Stream upload to NFS; insert videos + jobs rows; enqueue transcription.
    Thumbnail is grabbed in a background thread right after the upload lands."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"unsupported file type {ext!r}")

    vid = str(uuid.uuid4())
    dest_dir = Path(settings.media_root) / "videos" / user_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{vid}{ext}"

    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(settings.chunk_size)
                if not chunk:
                    break
                out.write(chunk)
    except OSError:
        dest.unlink(missing_ok=True)
        log.exception("storage write failed")
        raise HTTPException(500, "storage write failed")

    row = {
        "id": vid,
        "user_id": user_id,
        "filename": file.filename,
        "storage_path": f"videos/{user_id}/{vid}{ext}",
        "status": "queued",
        "size_bytes": dest.stat().st_size,
    }
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

    # Thumbnail in a background thread - do not delay the 201 response on ffmpeg.
    def _thumb():
        try:
            grab_thumbnail(dest)
        except Exception:
            log.exception("post-upload thumbnail failed (non-fatal)")
    threading.Thread(target=_thumb, daemon=True).start()

    return JSONResponse(status_code=201, content={**row, "job_id": job_id})
