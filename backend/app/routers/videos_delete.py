"""Video deletion endpoint."""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.services.supabase_client import admin_client
from app.services.auth import get_current_user

router = APIRouter()

ARTIFACT_EXTS = (".srt", ".vtt", ".docx", ".txt", ".pdf", ".thumb.jpg")


@router.delete("/{video_id}")
def delete_video(video_id: str, user_id: str = Depends(get_current_user)):
    """Delete a video: DB rows (cascade) + original file + generated artifacts on NFS."""
    r = (
        admin_client().table("videos")
        .select("id, filename, storage_path")
        .eq("id", video_id).eq("user_id", user_id)
        .limit(1).execute()
    )
    if not r.data:
        raise HTTPException(404, "not found")
    v = r.data[0]

    # files first (DB row is the source of truth for what to remove)
    src = Path(settings.media_root) / v["storage_path"]
    removed = []
    try:
        if src.exists():
            src.unlink()
            removed.append(src.name)
        stem = src.stem
        # every artifact this video can own: plain exports, dual-mode "-generic" exports,
        # and the thumbnail. Glob on the UUID stem so new export kinds can never leak again.
        candidates = [src.parent / (stem + e) for e in ARTIFACT_EXTS]
        candidates += sorted(src.parent.glob(stem + "-generic*"))
        for art in candidates:
            try:
                if art.is_file():
                    art.unlink()
                    removed.append(art.name)
            except OSError as e:
                print(f"warn: could not remove {art}: {e}")
        # drop the user dir if now empty (keep tree tidy)
        try:
            src.parent.rmdir()
        except OSError:
            pass  # not empty - other videos live here
    except OSError as e:
        raise HTTPException(500, f"storage delete failed: {e}")

    admin_client().table("videos").delete().eq("id", video_id).execute()
    return {"deleted": video_id, "files_removed": len(removed)}
