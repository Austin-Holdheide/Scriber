"""Requeue stale transcription jobs + converge cancelled ones.

1) A job whose stage is extracting/transcribing/writing but whose updated_at is older
   than STALE_MINUTES is dead (worker restarted/crashed mid-job - RQ removes the job
   from its registries on hard kill, DB row stays behind). This re-enqueues it.

2) A job with stage=cancel_requested that stayed stale means the worker never saw the
   flag (worker dead at the time). Converge it to cancelled so the UI is not stuck.

Run by systemd timer on 202 every minute. Idempotent: requeue updates updated_at,
so a job is only requeued once per staleness window. Heartbeats (5s) keep live jobs
from ever looking stale.
"""""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.supabase_client import admin_client  # noqa: E402
from app.services.queue import enqueue_transcription  # noqa: E402

STALE_MINUTES = float(os.getenv("STALE_MINUTES", "3"))


def main():
    now = datetime.utcnow()
    cutoff = (now - timedelta(minutes=STALE_MINUTES)).isoformat()

    # 1) stale ACTIVE jobs -> requeue
    r = (
        admin_client().table("jobs")
        .select("id,video_id,stage,updated_at,videos(storage_path)")
        .in_("stage", ["queued", "extracting", "transcribing", "writing"])
        .lt("updated_at", cutoff)
        .execute()
    )
    requeued = 0
    for job in r.data:
        jid = job["id"]
        vid = job["video_id"] if "video_id" in job else None
        sp = None
        vv = job.get("videos")
        if isinstance(vv, dict):
            sp = vv.get("storage_path")
            vid = vv.get("id", vid)
        if not sp or not vid:
            continue
        print(f"stale job {jid} (stage={job['stage']}, updated={job['updated_at']}) -> requeue")
        try:
            if job["stage"] == "diarizing":
                from app.services.queue import enqueue_diarization
                enqueue_diarization(job_id=jid, video_id=vid, storage_path=sp)
            else:
                enqueue_transcription(job_id=jid, video_id=vid, storage_path=sp)
            requeued += 1
        except Exception as e:
            print(f"  enqueue failed: {e}")

    # 2) stale cancel_requested -> converge to cancelled (worker never saw the flag)
    rc = (
        admin_client().table("jobs")
        .select("id,video_id")
        .eq("stage", "cancel_requested")
        .lt("updated_at", cutoff)
        .execute()
    )
    converged = 0
    for job in rc.data:
        print(f"stale cancel_requested job {job['id']} -> cancelled")
        admin_client().table("jobs").update(
            {"stage": "cancelled", "progress": 0, "cancel_requested": False, "updated_at": "now()"}
        ).eq("id", job["id"]).execute()
        if job.get("video_id"):
            admin_client().table("videos").update({"status": "cancelled"}).eq("id", job["video_id"]).execute()
        converged += 1

    print(f"requeued {requeued} stale job(s), converged {converged} cancelled job(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
