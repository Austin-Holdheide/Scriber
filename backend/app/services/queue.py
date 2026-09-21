"""Enqueue transcription/diarization jobs (API side, runs on 202)."""
from rq import Queue
from redis import Redis

from app.config import settings

_redis = None
_queue = None
_dq = None


def get_queue() -> Queue:
    global _redis, _queue
    if _queue is None:
        redis_host = getattr(settings, "redis_host", "192.168.1.203")
        _redis = Redis(host=redis_host, port=6379, db=0)
        _queue = Queue("transcribe-gpu", connection=_redis)
    return _queue


def get_diarize_queue() -> Queue:
    """Separate queue so diarization never blocks transcription (and vice versa)."""
    global _redis, _dq
    if _dq is None:
        redis_host = getattr(settings, "redis_host", "192.168.1.203")
        _redis = Redis(host=redis_host, port=6379, db=0)
        _dq = Queue("diarize-gpu", connection=_redis)
    return _dq


def _purge_stale(rq_job_id: str, q: Queue):
    from rq.job import Job
    try:
        Job.fetch(rq_job_id, connection=q.connection).delete()
    except Exception:
        pass


def enqueue_transcription(job_id: str, video_id: str, storage_path: str, language: str | None = None):
    """Worker imports app.workers.tasks.transcribe_job from ITS OWN venv (203/204/205).

    Deterministic RQ job id (scriber-<jobs.id>): lets /cancel fetch the job without
    scanning the queue, and RQ rejects a duplicate id while one is still queued
    (protects against sweeper/API double-enqueue of the same row).
    """
    q = get_queue()
    _purge_stale(f"scriber-{job_id}", q)
    q.enqueue(
        "app.workers.tasks.transcribe_job",
        job_row_id=job_id, video_id=video_id, storage_path=storage_path, language=language,
        job_id=f"scriber-{job_id}",
        job_timeout=3600 * 4, result_ttl=3600, failure_ttl=3600,
    )


def enqueue_diarization(job_id: str, video_id: str, storage_path: str):
    """GPU-only diarize queue (204/205 listen on diarize-gpu + transcribe-gpu).
    Deterministic id diarize-<jobs.id> for the same cancel/purge guarantees."""
    q = get_diarize_queue()
    _purge_stale(f"diarize-{job_id}", q)
    q.enqueue(
        "app.workers.diarize_tasks.diarize_job",
        job_row_id=job_id, video_id=video_id, storage_path=storage_path,
        job_id=f"diarize-{job_id}",
        job_timeout=3600 * 6, result_ttl=3600, failure_ttl=3600,
    )
