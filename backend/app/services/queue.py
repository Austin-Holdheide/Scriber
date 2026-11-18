"""Enqueue transcription/diarization jobs (API side, runs on 202).

Priority lanes (F-8). A paying account's upload must never sit behind free traffic, and RQ has no
per-job priority — only queue order, where a worker pops the first queue in its list that has
anything in it. So transcription is split into two queues and the workers read the paid one first:

    transcribe-high   premium + admin
    diarize-gpu       premium only (speaker separation)
    transcribe-low    free

Lane order is the whole mechanism: a Pro upload queued behind twenty free ones starts as soon as
the current job finishes, while the free ones keep their FIFO order instead of being interleaved
or displaced (which is what `at_front` would do — free work could starve forever).

Adding a lane here means adding it to the worker list too (`app/workers/worker.py`, env
`RQ_QUEUES`), or jobs pile up silently in a queue nobody reads.
"""
from rq import Queue
from redis import Redis

from app.config import settings

LANE_HIGH = "high"
LANE_LOW = "low"
LANES = (LANE_HIGH, LANE_LOW)
DIARIZE_QUEUE = "diarize-gpu"

_redis = None
_queues: dict[str, Queue] = {}
_dq = None


def _conn() -> Redis:
    global _redis
    if _redis is None:
        redis_host = getattr(settings, "redis_host", "192.168.1.203")
        _redis = Redis(host=redis_host, port=6379, db=0)
    return _redis


def lane_queue_name(lane: str | None) -> str:
    """Map a lane to its queue name, defaulting anything unknown to the free lane."""
    return f"transcribe-{lane if lane in LANES else LANE_LOW}"


def get_queue(lane: str = LANE_LOW) -> Queue:
    name = lane_queue_name(lane)
    q = _queues.get(name)
    if q is None:
        q = _queues[name] = Queue(name, connection=_conn())
    return q


def get_diarize_queue() -> Queue:
    """Separate queue so diarization never blocks transcription (and vice versa)."""
    global _dq
    if _dq is None:
        _dq = Queue(DIARIZE_QUEUE, connection=_conn())
    return _dq


def _purge_stale(rq_job_id: str, connection: Redis):
    """Drop a job id left behind by an interrupted enqueue.

    Fetched by id on the connection rather than through a queue, so it does not matter which lane
    the previous attempt landed in.
    """
    from rq.job import Job
    try:
        Job.fetch(rq_job_id, connection=connection).delete()
    except Exception:
        pass


def enqueue_transcription(job_id: str, video_id: str, storage_path: str,
                          language: str | None = None, lane: str = LANE_LOW):
    """Worker imports app.workers.tasks.transcribe_job from ITS OWN venv (203/204/205).

    Deterministic RQ job id (scriber-<jobs.id>): lets /cancel fetch the job without
    scanning the queue, and RQ rejects a duplicate id while one is still queued
    (protects against sweeper/API double-enqueue of the same row).

    `lane` comes from the plan (`quota.Plan.queue`); the default is the free lane so a caller
    that forgets it under-serves a paid account rather than over-serving a free one.
    """
    q = get_queue(lane)
    _purge_stale(f"scriber-{job_id}", q.connection)
    q.enqueue(
        "app.workers.tasks.transcribe_job",
        job_row_id=job_id, video_id=video_id, storage_path=storage_path, language=language,
        job_id=f"scriber-{job_id}",
        job_timeout=3600 * 4, result_ttl=3600, failure_ttl=3600,
    )


def enqueue_diarization(job_id: str, video_id: str, storage_path: str):
    """GPU-only diarize queue (204/205 listen on diarize-gpu).
    Deterministic id diarize-<jobs.id> for the same cancel/purge guarantees."""
    q = get_diarize_queue()
    _purge_stale(f"diarize-{job_id}", q.connection)
    q.enqueue(
        "app.workers.diarize_tasks.diarize_job",
        job_row_id=job_id, video_id=video_id, storage_path=storage_path,
        job_id=f"diarize-{job_id}",
        job_timeout=3600 * 24, result_ttl=3600, failure_ttl=3600,
    )
