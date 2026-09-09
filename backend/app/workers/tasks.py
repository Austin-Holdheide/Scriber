"""Transcription job - the heart of the pipeline.

Job stages (mirrored into jobs table for Realtime):
  extracting  - ffmpeg -> 16k mono wav
  transcribing - faster-whisper int8
  writing     - segments + transcript rows, SRT/VTT artifacts
"""
import logging
import math
import subprocess
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path

from faster_whisper import WhisperModel

from app.worker_config import wsettings
from app.services.supabase_client import admin_client

log = logging.getLogger("scriber.worker")

# model is loaded once per worker process and kept warm
_model = None


def get_model():
    global _model
    if _model is None:
        kw = {}
        if wsettings.device == "cpu":
            kw["cpu_threads"] = wsettings.cpu_threads
        log.info("loading model %s device=%s compute=%s", wsettings.model_size, wsettings.device, wsettings.compute_type)
        t0 = time.time()
        _model = WhisperModel(
            wsettings.model_size,
            device=wsettings.device,
            compute_type=wsettings.compute_type,
            **kw,
        )
        log.info("model loaded in %.1fs", time.time() - t0)
    return _model


def _set_job(job_id: str, stage: str, progress: int, error: str | None = None):
    admin_client().table("jobs").update(
        {"stage": stage, "progress": progress, "error": error, "updated_at": "now()"}
    ).eq("id", job_id).execute()


def _extract_audio(video_path: str, out_wav: str):
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", out_wav],
        check=True, capture_output=True,
    )


def _fmt_ts(ms: int, srt: bool = False) -> str:
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms2 = divmod(rem, 1000)
    if srt:
        return f"{h:02d}:{m:02d}:{s:02d},{ms2:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}.{ms2:03d}"


def transcribe_job(job_row_id: str, video_id: str, storage_path: str, language: str | None = None):
    """Main RQ entrypoint."""
    src = Path(wsettings.media_root) / storage_path
    if not src.exists():
        _set_job(job_row_id, "failed", 0, f"source missing: {src}")
        admin_client().table("videos").update({"status": "failed"}).eq("id", video_id).execute()
        return

    try:
        # 1. extract
        _set_job(job_row_id, "extracting", 5)
        tmp = Path(tempfile.mkdtemp(prefix="scriber-"))
        wav = tmp / "audio.wav"
        _extract_audio(str(src), str(wav))

        # 2. transcribe
        _set_job(job_row_id, "transcribing", 15)
        model = get_model()
        # VAD filtering can drift timestamps on long files (podcasts w/ intros/music):
        # speech regions are mapped back with accumulated error (~60s over 50min observed).
        # Short clips keep VAD (faster, kills silence hallucinations); long files get exact
        # timestamps at the cost of some speed. Duration via ffprobe (info comes from
        # transcribe() which we haven't called yet).
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
                check=True, capture_output=True, text=True,
            )
            audio_duration_s = float(probe.stdout.strip())
        except Exception:
            audio_duration_s = 0.0
        use_vad = audio_duration_s < 600
        segments_iter, info = model.transcribe(str(wav), language=language, vad_filter=use_vad)
        segments = []
        last_pulse = time.time()
        for seg in segments_iter:
            segments.append({
                "start_ms": int(seg.start * 1000),
                "end_ms": int(seg.end * 1000),
                "text": seg.text.strip(),
                "confidence": round(float(seg.avg_logprob), 3) if seg.avg_logprob else None,
            })
            if time.time() - last_pulse > 5:  # heartbeat every 5s
                # progress: 15-85 window proportional to audio position
                pct = 15 + int(70 * min(seg.end / max(info.duration, 0.001), 1.0))
                _set_job(job_row_id, "transcribing", pct)
                last_pulse = time.time()

        if not segments:
            raise RuntimeError("no speech detected")

        # 3. write
        _set_job(job_row_id, "writing", 88)
        full_text = " ".join(s["text"] for s in segments)
        tr = admin_client().table("transcripts").insert({
            "video_id": video_id,
            "model": f"{wsettings.model_size}/{wsettings.device}/{wsettings.compute_type}",
            "full_text": full_text,
        }).execute()
        transcript_id = tr.data[0]["id"]

        rows = [{**s, "transcript_id": transcript_id} for s in segments]
        for i in range(0, len(rows), 500):  # chunked insert
            admin_client().table("segments").insert(rows[i:i + 500]).execute()

        # SRT/VTT artifacts next to the video on NFS
        srt = tmp / "out.srt"
        vtt = tmp / "out.vtt"
        with open(srt, "w") as f:
            for i, s in enumerate(segments, 1):
                f.write(f"{i}\n{_fmt_ts(s['start_ms'], True)} --> {_fmt_ts(s['end_ms'], True)}\n{s['text']}\n\n")
        with open(vtt, "w") as f:
            f.write("WEBVTT\n\n")
            for s in segments:
                f.write(f"{_fmt_ts(s['start_ms'])} --> {_fmt_ts(s['end_ms'])}\n{s['text']}\n\n")

        base = src.parent / src.stem
        srt_dest = base.with_suffix(".srt")
        vtt_dest = base.with_suffix(".vtt")
        import shutil
        shutil.move(srt.as_posix(), srt_dest.as_posix())
        shutil.move(vtt.as_posix(), vtt_dest.as_posix())

        admin_client().table("transcripts").update({
            "srt_path": srt_dest.name, "vtt_path": vtt_dest.name,
        }).eq("id", transcript_id).execute()
        admin_client().table("videos").update({"status": "done", "language": info.language}).eq("id", video_id).execute()
        _set_job(job_row_id, "done", 100)

        log.info("job %s done: %d segments", job_row_id, len(segments))

    except Exception as e:
        log.exception("job failed")
        _set_job(job_row_id, "failed", 0, str(e)[:500])
        admin_client().table("videos").update({"status": "failed"}).eq("id", video_id).execute()
    finally:
        subprocess.run(["rm", "-rf", tmp.as_posix()])
