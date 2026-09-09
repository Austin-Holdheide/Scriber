"""Enqueue transcription jobs (API side, runs on 202)."""
from rq import Queue
from redis import Redis

from app.config import settings

_redis = None
_queue = None


def get_queue() -> Queue:
    global _redis, _queue
    if _queue is None:
        redis_host = getattr(settings, "redis_host", "192.168.1.203")
        _redis = Redis(host=redis_host, port=6379, db=0)
        _queue = Queue("transcribe-gpu", connection=_redis)
    return _queue


def enqueue_transcription(job_id: str, video_id: str, storage_path: str, language: str | None = None):
    """Worker imports app.workers.tasks.transcribe_job from ITS OWN venv (203/204/205)."""
    q = get_queue()
    # note: worker CTs have /opt/scriber/backend on PYTHONPATH (systemd unit sets it)
    q.enqueue(
        "app.workers.tasks.transcribe_job",
        job_row_id=job_id, video_id=video_id, storage_path=storage_path, language=language,
        job_timeout=3600 * 4, result_ttl=3600, failure_ttl=3600,
    )
