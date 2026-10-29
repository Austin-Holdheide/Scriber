"""Video upload (streaming) endpoint.

Quota enforcement happens in three places, in this order:
  1. before reading a byte   - plan lookup + rolling upload allowance   (429)
  2. while streaming         - aborts as soon as the body passes the plan's byte cap (413)
  3. after the file lands    - ffprobe duration against the plan's length cap (422)
Only a file that clears all three is stored, enqueued and metered.

Small files use this endpoint. Anything a proxy would refuse (Cloudflare caps a
single request body at 100 MB on Free/Pro) goes through the chunked endpoints in
`videos_chunked.py`, which finish in the same place: `services.ingest`.
"""
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.auth import get_current_user
from app.services import quota
from app.services.ingest import finalize_upload

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

    body = finalize_upload(user_id=user_id, dest=dest, filename=file.filename or f"upload{ext}",
                           ext=ext, plan=plan, vid=vid)
    return JSONResponse(status_code=201, content=body)
