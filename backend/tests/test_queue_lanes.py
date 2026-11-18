"""F-8 queue lanes: the tier decides which queue an upload lands in.

Two rules worth pinning, because both fail silently:
  - premium/admin go to `high`, free to `low` — a paying account must never sit behind free traffic
  - an unknown or missing plan falls to `low` (under-serve a paid account, never over-serve a free one)
"""
import pytest

from app.services import quota
from app.services import queue as q
from app.workers.worker import QUEUES_CPU, QUEUES_CUDA, queue_names


# ------------------------------------------------------------------ plan -> lane

@pytest.mark.parametrize("plan,lane", [
    ("free", "low"),
    ("premium", "high"),
    ("admin", "high"),
])
def test_each_plan_has_its_lane(plan, lane):
    assert quota.lane_for_plan(plan) == lane


@pytest.mark.parametrize("plan", [None, "", "FREE", "enterprise", "premium "])
def test_unknown_plans_fall_to_the_free_lane(plan):
    assert quota.lane_for_plan(plan) == "low"


def test_lane_comes_from_the_same_table_as_the_limits():
    """The lane is a field of Plan, not a second opinion about who is premium."""
    for name, plan in quota.PLANS.items():
        assert quota.lane_for_plan(name) == plan.queue


def test_lane_for_user_asks_the_plan_lookup(monkeypatch):
    monkeypatch.setattr(quota, "plan_name_for", lambda uid: "premium" if uid == "pro" else "free")
    assert quota.lane_for_user("pro") == "high"
    assert quota.lane_for_user("someone") == "low"


# ------------------------------------------------------------------ queue names

def test_lane_names_are_transcribe_prefixed():
    assert q.lane_queue_name("high") == "transcribe-high"
    assert q.lane_queue_name("low") == "transcribe-low"


def test_bogus_lane_never_creates_a_queue():
    assert q.lane_queue_name("urgent") == "transcribe-low"
    assert q.lane_queue_name(None) == "transcribe-low"


# ------------------------------------------------------------------ enqueue routing

class _Recorder:
    """Stands in for an RQ Queue and records what would have been enqueued."""

    def __init__(self, name):
        self.name = name
        self.connection = None
        self.calls = []

    def enqueue(self, func, **kwargs):
        self.calls.append((func, kwargs))


def test_premium_upload_is_enqueued_on_the_high_lane(monkeypatch):
    rec = _Recorder("transcribe-high")
    monkeypatch.setattr(q, "get_queue", lambda lane="low": (rec, setattr(rec, "lane", lane))[0])
    q.enqueue_transcription(job_id="j1", video_id="v1", storage_path="videos/u/v1.mp4", lane="high")
    assert rec.lane == "high"
    assert rec.calls[0][0] == "app.workers.tasks.transcribe_job"
    assert rec.calls[0][1]["job_id"] == "scriber-j1"


def test_default_lane_is_free(monkeypatch):
    rec = _Recorder("transcribe-low")
    monkeypatch.setattr(q, "get_queue", lambda lane="low": (rec, setattr(rec, "lane", lane))[0])
    q.enqueue_transcription(job_id="j2", video_id="v2", storage_path="videos/u/v2.mp4")
    assert rec.lane == "low"


# ------------------------------------------------------------------ worker order
def test_gpu_worker_reads_paid_lane_first():
    names = queue_names(device="cuda", env={})
    assert names == QUEUES_CUDA
    assert names[0] == "transcribe-high", "a paid job must never wait behind the free lane"
    assert names.index("transcribe-low") > names.index("transcribe-high")


def test_cpu_worker_has_no_diarize_queue():
    names = queue_names(device="cpu", env={})
    assert names == QUEUES_CPU
    assert "diarize-gpu" not in names


def test_rq_queues_env_wins():
    names = queue_names(device="cuda", env={"RQ_QUEUES": "transcribe-low, transcribe-high"})
    assert names == ["transcribe-low", "transcribe-high"]


def test_prod_fallback_pin_is_expressible():
    """203 is pinned to the free lane only, so a CPU box never takes a paying customer's job."""
    assert queue_names(device="cpu", env={"RQ_QUEUES": "transcribe-low"}) == ["transcribe-low"]


def test_legacy_single_queue_is_appended_not_preferred():
    names = queue_names(device="cpu", env={"RQ_QUEUE": "transcribe-gpu"})
    assert names[:2] == QUEUES_CPU
    assert names[-1] == "transcribe-gpu"


def test_legacy_queue_already_in_the_list_is_not_duplicated():
    assert queue_names(device="cpu", env={"RQ_QUEUE": "transcribe-low"}) == QUEUES_CPU


# ------------------------------------------------------------------ ingest wiring

def test_upload_asks_the_plan_which_lane(monkeypatch, tmp_path):
    """The lane must come from the plan at the moment of upload, not from a default."""
    from app.services import ingest, quota as qq

    seen = {}
    monkeypatch.setattr(ingest, "enqueue_transcription",
                        lambda **kw: seen.update(kw))
    monkeypatch.setattr(ingest, "probe_duration_s", lambda _p: 60.0)
    monkeypatch.setattr(ingest, "grab_thumbnail", lambda _p: None)
    monkeypatch.setattr(qq, "record", lambda *a, **k: None)

    class _Q:
        def table(self, _n): return self
        def insert(self, _row): return self
        def execute(self): return type("R", (), {"data": []})()

    monkeypatch.setattr(ingest, "admin_client", lambda: _Q())

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x" * 32)
    plan = quota.PLANS["premium"]
    ingest.finalize_upload(user_id="11111111-1111-1111-1111-111111111111",
                           dest=src, filename="clip.mp4", ext=".mp4", plan=plan)
    assert seen["lane"] == "high"

    src2 = tmp_path / "clip2.mp4"
    src2.write_bytes(b"x" * 32)
    seen.clear()
    ingest.finalize_upload(user_id="11111111-1111-1111-1111-111111111111",
                           dest=src2, filename="clip2.mp4", ext=".mp4", plan=quota.PLANS["free"])
    assert seen["lane"] == "low"
