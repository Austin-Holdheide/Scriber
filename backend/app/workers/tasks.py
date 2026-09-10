"""Transcription job - the heart of the pipeline.

Job stages (mirrored into jobs table for Realtime):
  extracting  - ffmpeg -> 16k mono wav
  transcribing - faster-whisper int8
  writing     - segments + transcript rows, SRT/VTT artifacts
"""
import logging
import math
import os
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

CHUNK_SECONDS = 600  # 10-minute transcription chunks for long files

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

        # 2. transcribe - chunked for long files
        _set_job(job_row_id, "transcribing", 15)
        model = get_model()
        # Two constraints that bite long files:
        #  - whole-file decode without VAD OOMs the 8GB CT (3.7h audio ~ 850MB float32 + features)
        #  - VAD avoids the OOM but its region remap drifts timestamps on long files
        # Solution: fixed 10-minute chunks, VAD off inside each chunk. Constant memory,
        # exact timestamps, progress per chunk. Single-file path keeps the old behavior.
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
            check=True, capture_output=True, text=True,
        )
        audio_duration_s = float(probe.stdout.strip() or 0)

        segments = []
        detected_lang = None
        last_pulse = time.time()

        def _run_chunk(chunk_path: str, offset_s: float, base_pct: float, span: float):
            nonlocal detected_lang, last_pulse
            segs_iter, info = model.transcribe(chunk_path, language=language, vad_filter=False)
            if detected_lang is None and info.language:
                detected_lang = info.language
            for seg in segs_iter:
                segments.append({
                    "start_ms": int((offset_s + seg.start) * 1000),
                    "end_ms": int((offset_s + seg.end) * 1000),
                    "text": seg.text.strip(),
                    "confidence": round(float(seg.avg_logprob), 3) if seg.avg_logprob else None,
                })
                if time.time() - last_pulse > 5:
                    pct = int(base_pct + span * min(seg.end / max(info.duration, 0.001), 1.0))
                    _set_job(job_row_id, "transcribing", pct)
                    last_pulse = time.time()

        if audio_duration_s <= CHUNK_SECONDS:
            _run_chunk(str(wav), 0.0, 15, 70)
        else:
            n_chunks = int(audio_duration_s / CHUNK_SECONDS) + 1
            for ci in range(n_chunks):
                offset = ci * CHUNK_SECONDS
                chunk_wav = tmp / f"chunk_{ci:03d}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(offset), "-t", str(CHUNK_SECONDS),
                     "-i", str(wav), "-ac", "1", "-ar", "16000", "-f", "wav", str(chunk_wav)],
                    check=True, capture_output=True,
                )
                base_pct = 15 + int(70 * ci / n_chunks)
                _run_chunk(str(chunk_wav), offset, base_pct, 70.0 / n_chunks)
                os.unlink(chunk_wav)  # constant tmp usage

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
        admin_client().table("videos").update({"status": "done", "language": detected_lang}).eq("id", video_id).execute()
        _set_job(job_row_id, "done", 100)

        log.info("job %s done: %d segments", job_row_id, len(segments))

    except Exception as e:
        log.exception("job failed")
        _set_job(job_row_id, "failed", 0, str(e)[:500])
        admin_client().table("videos").update({"status": "failed"}).eq("id", video_id).execute()
    finally:
        subprocess.run(["rm", "-rf", tmp.as_posix()])
