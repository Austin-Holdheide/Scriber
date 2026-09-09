"""Requeue stale transcription jobs.

A job whose stage is extracting/transcribing/writing but whose updated_at is older
than STALE_MINUTES is dead (worker restarted/crashed mid-job - RQ removes the job
from its registries on hard kill, DB row stays behind). This re-enqueues it.

Run by systemd timer on 202 every minute. Idempotent: requeue updates updated_at,
so a job is only requeued once per staleness window. Heartbeats (5s) keep live jobs
from ever looking stale.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.supabase_client import admin_client  # noqa: E402
from app.services.queue import enqueue_transcription  # noqa: E402

STALE_MINUTES = float(os.getenv("STALE_MINUTES", "3"))


def main():
    cutoff = (datetime.utcnow() - timedelta(minutes=STALE_MINUTES)).isoformat()
    r = (
        admin_client().table("jobs")
        .select("id,video_id,stage,updated_at,videos(storage_path)")
        .in_("stage", ["queued", "extracting", "transcribing", "writing"])
        .lt("updated_at", cutoff)
        .execute()
    )
    # note: 'queued' with fresh updated_at = waiting in redis (normal, skip via lt filter);
    # a queued job older than the window with an EMPTY redis queue is also stale.
    requeued = 0
    for job in r.data:
        jid = job["id"]
        vid = job["video_id"] if "video_id" in job else job["videos"]["id"] if isinstance(job.get("videos"), dict) else None
        # supabase-py returns nested videos as dict
        sp = None
        vv = job.get("videos")
        if isinstance(vv, dict):
            sp = vv.get("storage_path")
            vid = vv.get("id", vid)
        if not sp:
            continue
        print(f"stale job {jid} (stage={job['stage']}, updated={job['updated_at']}) -> requeue")
        try:
            enqueue_transcription(job_id=jid, video_id=vid, storage_path=sp)
            requeued += 1
        except Exception as e:
            print(f"  enqueue failed: {e}")
    print(f"requeued {requeued} stale job(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
