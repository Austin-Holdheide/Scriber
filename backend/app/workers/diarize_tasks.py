"""W10: standalone diarization job - labels EXISTING segments in place.

Runs after transcription (via the "Detect speakers" button). Does NOT re-transcribe:
- fetches existing segment midpoints from the DB
- runs pyannote speaker-diarization-3.1 on GPU over the source media
- maps each segment midpoint to the overlapping speaker turn
- bulk-updates segments.speaker (SPEAKER_00 -> "Speaker 1", ...)
- updates the transcript row's speakers list for the rename UI
Job stages: queued -> diarizing (15..90) -> done
"""
import logging
import subprocess
import tempfile as _tempfile
import time
from pathlib import Path

import torch

from app.worker_config import wsettings
from app.services.supabase_client import admin_client
from app.services.notify import notify

log = logging.getLogger("scriber.diarize")

_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pyannote.audio import Pipeline
        _pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
        _pipeline.to(torch.device("cuda"))
        log.info("pyannote pipeline loaded on %s", torch.device("cuda"))
    return _pipeline


def _set_job(job_id: str, stage: str, progress: int, error: str | None = None):
    admin_client().table("jobs").update(
        {"stage": stage, "progress": progress, "error": error, "updated_at": "now()"}
    ).eq("id", job_id).execute()


def _check_cancel(job_id: str):
    r = (admin_client().table("jobs")
         .select("cancel_requested").eq("id", job_id).limit(1).execute())
    if r.data and r.data[0].get("cancel_requested"):
        raise RuntimeError("cancelled")


def diarize_job(job_row_id: str, video_id: str, storage_path: str):
    """Main entrypoint: label existing segments with speaker names."""
    src = Path(wsettings.media_root) / storage_path
    uid = None

    try:
        jrow = admin_client().table("jobs").select("user_id").eq("id", job_row_id).limit(1).execute()
        uid = jrow.data[0]["user_id"] if jrow.data else None
    except Exception:
        pass

    tmp = None
    try:
        if not src.exists():
            raise RuntimeError(f"source missing: {src}")

        _set_job(job_row_id, "diarizing", 15)

        # 1) existing segments from the DB (paged - 1000-row cap defense)
        t = (admin_client().table("transcripts")
             .select("id").eq("video_id", video_id)
             .order("created_at", desc=True).limit(1).execute())
        if not t.data:
            raise RuntimeError("no transcript")
        transcript_id = t.data[0]["id"]

        segs, offset, page = [], 0, 1000
        while True:
            r = (admin_client().table("segments")
                 .select("id,start_ms,end_ms").eq("transcript_id", transcript_id)
                 .order("start_ms").range(offset, offset + page - 1).execute())
            segs.extend(r.data)
            if len(r.data) < page:
                break
            offset += page
        if not segs:
            raise RuntimeError("no segments to label")
        log.info("diarizing %d segments", len(segs))

        # 2) extract 16k mono wav (pyannote wants a file path)
        _check_cancel(job_row_id)
        tmp = Path(_tempfile.mkdtemp(prefix="scriber-diar-"))
        wav = tmp / "audio.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
            check=True, capture_output=True,
        )

        # 3) run the pipeline on GPU
        _set_job(job_row_id, "diarizing", 30)
        _check_cancel(job_row_id)
        pipeline = get_pipeline()
        t0 = time.time()
        annotation = pipeline(str(wav))
        took = time.time() - t0
        log.info("diarization done in %.0fs", took)

        # 4) map segment midpoints -> speaker turns
        _set_job(job_row_id, "diarizing", 75)
        turns = [(turn.start * 1000, turn.end * 1000, spk)
                 for turn, _, spk in annotation.itertracks(yield_label=True)]
        turns.sort()
        from collections import defaultdict as _dd
        _dur = _dd(float)
        for _st, _en, _sp in turns:
            _dur[_sp] += (_en - _st)
        total_speech = sum(_dur.values())

        import bisect
        starts = [t[0] for t in turns]

        def speaker_at(ms: int) -> str | None:
            """Speaker whose turn overlaps the midpoint (latest-starting match wins)."""
            mid = (int(ms) / 1000.0) if False else ms
            i = bisect.bisect_right(starts, ms) - 1
            for st, en, spk in turns[max(0, i - 2): i + 3]:
                if st <= ms < en:
                    return spk
            # fallback: nearest turn within 1.5s
            best, bd = None, 1500
            for st, en, spk in turns:
                d = min(abs(ms - st), abs(ms - en))
                if d < bd:
                    best, bd = spk, d
            return best

        # merge micro-clusters: speakers with <5% of total speech time fold into the
        # dominant speaker (music stings / one-word interjections)
        from collections import defaultdict
        dur_by_spk = defaultdict(float)
        for st, en, spk in turns:
            dur_by_spk[spk] += (en - st)
        dominant = {spk for spk, d in dur_by_spk.items() if d >= total_speech * 0.05}
        if dominant:
            fallback = sorted(dominant, key=lambda d: -dur_by_spk[d])[0]
            turns = [(st, en, (spk if spk in dominant else fallback)) for st, en, spk in turns]

        # stable human labels: SPEAKER_00 -> Speaker 1, ... (numbered by total speech time)
        order = sorted({spk for _, _, spk in turns}, key=lambda s: -dur_by_spk.get(s, 0))
        label_map = {raw_i: f"Speaker {i + 1}" for i, raw_i in enumerate(order)}

        # 5) bulk-update segments (chunks of 500 UPDATEs via individual eq - PostgREST
        #    has no bulk-update-by-different-values, so patch per distinct speaker per
        #    id-range is worse; per-segment PATCH in batches is fine at this scale)
        updates = []
        for s in segs:
            mid = (s["start_ms"] + s["end_ms"]) // 2
            spk = speaker_at(mid)
            if spk:
                updates.append((s["id"], label_map[spk]))

        for i in range(0, len(updates), 200):
            _check_cancel(job_row_id)
            chunk = updates[i:i + 200]
            for sid, label in chunk:
                admin_client().table("segments").update({"speaker": label}).eq("id", sid).execute()
            pct = 75 + int(15 * (i + len(chunk)) / max(len(updates), 1))
            _set_job(job_row_id, "diarizing", min(pct, 90))

        # 6) record speaker map on the transcript row (rename UI reads this)
        admin_client().table("transcripts").update({
            "speakers": label_map,
        }).eq("id", transcript_id).execute()

        admin_client().table("videos").update({"status": "done"}).eq("id", video_id).execute()
        _set_job(job_row_id, "done", 100)

        if uid:
            names = ", ".join(label_map.values())
            notify(uid, "Speaker detection done",
                   f"{src.name}: {len(turns)} turns -> {len(label_map)} speakers ({names}).",
                   tags="speech_balloon")
        log.info("diarize job done: %d segments labeled, %d speakers", len(updates), len(label_map))

    except RuntimeError as e:
        if "cancelled" in str(e).lower():
            _set_job(job_row_id, "cancelled", 0, None)
            admin_client().table("videos").update({"status": "done"}).eq("id", video_id).execute()
            if uid:
                notify(uid, "Speaker detection cancelled", src.name, tags="stop_sign")
        else:
            log.exception("diarize job failed")
            _set_job(job_row_id, "failed", 0, str(e)[:500])
            admin_client().table("videos").update({"status": "failed"}).eq("id", video_id).execute()
            if uid:
                notify(uid, "Speaker detection failed", f"{src.name}: {str(e)[:160]}",
                       priority="high", tags="warning")
    except Exception as e:
        log.exception("diarize job failed")
        _set_job(job_row_id, "failed", 0, str(e)[:500])
        admin_client().table("videos").update({"status": "failed"}).eq("id", video_id).execute()
        try:
            if uid:
                notify(uid, "Speaker detection failed", f"{src.name}: {str(e)[:160]}",
                       priority="high", tags="warning")
        except Exception:
            pass
    finally:
        if tmp is not None:
            subprocess.run(["rm", "-rf", tmp.as_posix()])
