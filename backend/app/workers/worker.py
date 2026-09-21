"""RQ worker entrypoint:  rq worker -s ... OR run this file directly."""
import logging
import sys
from pathlib import Path

# allow running from /opt/scriber/backend
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rq import Worker, Queue
from redis import Redis

from app.worker_config import wsettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

redis = Redis(host=wsettings.redis_host, port=wsettings.redis_port, db=0)

# GPU workers listen on their own priority queue FIRST, plus the shared fallback queue,
# plus the diarize queue. CPU workers only listen on the fallback (no diarization).
if wsettings.device == "cuda":
    queues = [Queue("transcribe-gpu", connection=redis),
              Queue("diarize-gpu", connection=redis),
              Queue(wsettings.queue_name, connection=redis)]
else:
    queues = [Queue(wsettings.queue_name, connection=redis)]

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--name", default=None)
    args = p.parse_args()
    name = args.name or f"worker-{wsettings.device}"
    w = Worker(queues, connection=redis, name=name)
    w.work()
