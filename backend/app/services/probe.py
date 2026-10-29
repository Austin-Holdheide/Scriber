"""Small ffprobe wrapper: we need a media file's duration to enforce plan length caps."""
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("scriber.probe")


def probe_duration_s(path: str | Path) -> float | None:
    """Duration in seconds, or None when ffprobe is missing/can't read the file."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        log.exception("ffprobe failed to run for %s", path)
        return None
    raw = (out.stdout or "").strip().splitlines()
    if not raw:
        log.warning("ffprobe returned nothing for %s (rc=%s, %s)", path, out.returncode, out.stderr.strip()[:200])
        return None
    try:
        value = float(raw[0].replace(",", "."))
    except ValueError:
        log.warning("ffprobe gave a non-numeric duration for %s: %r", path, raw[0])
        return None
    return value if value > 0 else None
