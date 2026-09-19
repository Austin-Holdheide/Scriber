"""Thumbnail helpers (shared API + worker - imports nothing heavy).

320px JPEG frame grabbed at ~2s. Stored next to the source as <stem>.thumb.jpg.
Deletion paths must remove that file (videos_delete does).
"""""
import subprocess
from pathlib import Path

from app.config import settings

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm"}


def thumb_path_for(storage_path: str) -> Path | None:
    """NFS path of the thumbnail for a stored video, or None for audio files."""
    src = Path(settings.media_root) / storage_path
    if src.suffix.lower() not in VIDEO_EXT:
        return None
    return src.parent / f"{src.stem}.thumb.jpg"


def grab_thumbnail(src: Path) -> bool:
    """Best-effort 320px frame grab next to the source file. Never raises."""
    if src.suffix.lower() not in VIDEO_EXT:
        return False
    thumb = src.parent / f"{src.stem}.thumb.jpg"
    if thumb.exists():
        return True
    for ss in ("2", "0"):  # 2s in; retry at 0 for very short clips
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", ss, "-i", str(src), "-frames:v", "1",
                 "-vf", "scale=320:-2", "-q:v", "3", str(thumb)],
                capture_output=True, timeout=120,
            )
        except Exception:
            return False
        if r.returncode == 0 and thumb.exists() and thumb.stat().st_size > 0:
            return True
        thumb.unlink(missing_ok=True)
    return False
