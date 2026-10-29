"""The tail end of every upload: probe, gate, record, enqueue.

Both the single-shot endpoint (`POST /api/videos/upload`) and the chunked one
(`POST /api/videos/upload/{id}/complete`) land here, so the length gate, the
database rows, the RQ enqueue and the usage event cannot drift apart.

Enforcement order is the same as before and must stay that way:
  1. before a byte   - plan lookup + rolling allowance            (429)  [caller]
  2. while writing   - abort when the byte cap is crossed          (413)  [caller]
  3. after the file  - ffprobe duration against the length cap     (422)  [here]
Only a file that clears all three is stored, enqueued and metered.
"""
import logging
import threading
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.services import quota
from app.services.probe import probe_duration_s
from app.services.queue import enqueue_transcription
from app.services.supabase_client import admin_client
from app.services.thumbs import grab_thumbnail

log = logging.getLogger("scriber.ingest")


def _thumb_async(dest: Path) -> None:
    """Grab a poster frame off the request path - ffmpeg must not delay the 201."""
    def _run():
        try:
            grab_thumbnail(dest)
        except Exception:
            log.exception("post-upload thumbnail failed (non-fatal)")
    threading.Thread(target=_run, daemon=True).start()


def finalize_upload(*, user_id: str, dest: Path, filename: str, ext: str,
                    plan: quota.Plan, vid: str | None = None) -> dict:
    """Turn a file that is already on disk into an accepted, queued video.

    Deletes `dest` and raises if the length cap rejects it, or if the database
    insert fails - an upload that is not accepted leaves nothing behind.
    """
    vid = vid or str(uuid.uuid4())

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
        "filename": filename,
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

    _thumb_async(dest)

    return {
        **row, "job_id": job_id, "plan": plan.name,
        "duration_s": round(duration_s, 3) if duration_s else None,
    }
