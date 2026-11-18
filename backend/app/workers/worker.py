"""RQ worker entrypoint:  rq worker -s ... OR run this file directly.

Queue order *is* the priority (F-8): a worker pops the first non-empty queue in its list, so the
paid lane is read before the free one. `RQ_QUEUES` overrides the list for a specific container.

    GPU (204/205)   transcribe-high, diarize-gpu, transcribe-low
    CPU (default)   transcribe-high, transcribe-low

Prod's 203 is pinned to `RQ_QUEUES=transcribe-low` on purpose: it is the fallback for free traffic
only, so a paid upload is never picked up by a CPU-only box while a P4 is idle.
"""
import logging
import os
import sys
from pathlib import Path
from typing import Mapping

# allow running from /opt/scriber/backend
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rq import Worker, Queue
from redis import Redis

from app.worker_config import wsettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

QUEUES_CUDA = ["transcribe-high", "diarize-gpu", "transcribe-low"]
QUEUES_CPU = ["transcribe-high", "transcribe-low"]


def queue_names(device: str | None = None, env: Mapping[str, str] | None = None) -> list[str]:
    """Queue list for this worker, paid lane first.

    Pure function so the ordering can be tested without redis. `RQ_QUEUES` (comma separated) wins;
    the legacy single `RQ_QUEUE` is honoured last so an old container keeps working, but it lands at
    the end of the list where it cannot outrank a lane.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    device = wsettings.device if device is None else device
    base = QUEUES_CUDA if device == "cuda" else QUEUES_CPU

    names = [n.strip() for n in (source.get("RQ_QUEUES") or "").split(",") if n.strip()]
    if names:
        return names

    legacy = (source.get("RQ_QUEUE") or "").strip()
    return base + ([legacy] if legacy and legacy not in base else [])


redis = Redis(host=wsettings.redis_host, port=wsettings.redis_port, db=0)
queues = [Queue(name, connection=redis) for name in queue_names()]

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--name", default=None)
    args = p.parse_args()
    name = args.name or f"worker-{wsettings.device}"
    logging.getLogger("scriber.worker").info(
        "listening on %s (device=%s)", ", ".join(q.name for q in queues), wsettings.device)
    w = Worker(queues, connection=redis, name=name)
    w.work()
