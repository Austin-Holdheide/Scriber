"""One-shot backfill: generate thumbnails for existing videos (skip when present).

Run on CT 202:  set -a; . /opt/scriber/.env; set +a; \
  /opt/scriber/venv/bin/python /opt/scriber/backend/scripts/backfill_thumbs.py
"""""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from app.config import settings
from app.services.supabase_client import admin_client
from app.services.thumbs import thumb_path_for, grab_thumbnail


def main():
    vids = admin_client().table("videos").select("id,storage_path").execute().data
    made = skipped = failed = 0
    for v in vids:
        sp = v["storage_path"]
        thumb = thumb_path_for(sp)
        if thumb is None:
            continue
        if thumb.exists():
            skipped += 1
            continue
        if grab_thumbnail(Path(settings.media_root) / sp):
            made += 1
            print("thumb ok:", Path(sp).name)
        else:
            failed += 1
            print("thumb FAILED:", Path(sp).name)
    print(f"backfill done: {made} made, {skipped} skipped, {failed} failed, of {len(vids)} videos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
