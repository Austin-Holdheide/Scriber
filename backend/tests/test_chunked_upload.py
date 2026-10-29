"""Chunked upload sessions - filesystem only, no database.

These pin the rules that make the chunked path safe to expose:
  - parts must arrive in order, and a retry learns where to resume (409 + next_index)
  - the plan byte cap aborts mid-part and leaves nothing extra on disk (413)
  - a session id is scoped to the account that created it (404 for anyone else)
  - only a fully received session is moved into videos/, and a refused one leaves
    no staged bytes behind

`complete_session` is tested without `finalize_upload`, so no Supabase, no RQ and
no ffprobe is touched here - the ingest path has its own coverage.
"""
import asyncio
import json
import os
import time

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import quota, uploads


@pytest.fixture(autouse=True)
def staging(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setenv("UPLOAD_PART_SIZE_MB", "1")
    return tmp_path


def _plan(name: str = "premium", max_upload_bytes: int = 100 * 1024 * 1024,
          max_duration_s: int = 86400, uploads_per_window: int = -1,
          diarizations_per_day: int = 10) -> quota.Plan:
    return quota.Plan(
        name=name,
        max_upload_bytes=max_upload_bytes,
        max_duration_s=max_duration_s,
        uploads_per_window=uploads_per_window,
        window_s=0,
        diarizations_per_day=diarizations_per_day,
        share_max_days=30,
        retention_days=0,
        queue="high",
    )


def _append(*args, **kw):
    """append_part is async because it drains the request stream; tests stay sync."""
    return asyncio.run(uploads.append_part(*args, **kw))


def _detail(exc: HTTPException) -> dict:
    assert isinstance(exc.value.detail, dict), "errors must carry a structured detail"
    return exc.value.detail


def test_part_size_is_under_the_cloudflare_body_cap():
    assert uploads.part_size() == 1024 * 1024
    os.environ.pop("UPLOAD_PART_SIZE_MB", None)
    assert uploads.part_size() == 64 * 1024 * 1024
    assert uploads.part_size() < 100 * 1024 * 1024


def test_session_starts_empty_and_reports_its_part_size():
    s = uploads.create_session("u1", "talk.mp4", 2 * 1024 * 1024, _plan())
    assert s["received_bytes"] == 0
    assert s["next_index"] == 0
    assert s["part_size"] == uploads.part_size()
    assert s["size_bytes"] == 2 * 1024 * 1024


def test_parts_append_in_order_and_advance_next_index():
    ps = uploads.part_size()
    s = uploads.create_session("u1", "talk.mp4", 2 * ps, _plan())
    uid = s["upload_id"]

    r0 = _append("u1", uid, 0, [b"a" * ps])
    assert r0["received_bytes"] == ps
    assert r0["next_index"] == 1

    r1 = _append("u1", uid, 1, [b"b" * ps])
    assert r1["received_bytes"] == 2 * ps
    assert r1["next_index"] == 2

    staged = uploads.session_dir("u1", uid) / "data.bin"
    assert staged.stat().st_size == 2 * ps


def test_append_consumes_an_async_stream():
    """The router passes request.stream(); a sync `for` over it raised TypeError."""
    ps = uploads.part_size()
    uid = uploads.create_session("u1", "talk.mp4", ps, _plan())["upload_id"]

    async def stream():
        yield b"a" * (ps // 2)
        yield b"b" * (ps - ps // 2)

    r = asyncio.run(uploads.append_part("u1", uid, 0, stream()))
    assert r["received_bytes"] == ps
    assert uploads.received_bytes("u1", uid) == ps


def test_out_of_order_part_is_refused_with_the_resume_point():
    ps = uploads.part_size()
    uid = uploads.create_session("u1", "talk.mp4", 2 * ps, _plan())["upload_id"]
    _append("u1", uid, 0, [b"a" * ps])

    with pytest.raises(HTTPException) as exc:
        _append("u1", uid, 0, [b"a" * ps])   # duplicate retry
    assert exc.value.status_code == 409
    d = _detail(exc)
    assert d["next_index"] == 1
    assert d["received_bytes"] == ps


def test_byte_cap_aborts_mid_part_and_leaves_no_extra_bytes():
    ps = uploads.part_size()
    uid = uploads.create_session("u1", "talk.mp4", 4 * ps, _plan(max_upload_bytes=ps + 10))["upload_id"]
    _append("u1", uid, 0, [b"a" * ps])

    with pytest.raises(HTTPException) as exc:
        _append("u1", uid, 1, [b"b" * 100])
    assert exc.value.status_code == 413
    assert _detail(exc)["error"] == "upload_too_large"
    # the refused part must not be left half-written
    assert uploads.received_bytes("u1", uid) == ps


def test_part_bigger_than_advertised_is_refused():
    ps = uploads.part_size()
    uid = uploads.create_session("u1", "talk.mp4", 4 * ps, _plan())["upload_id"]
    with pytest.raises(HTTPException) as exc:
        _append("u1", uid, 0, [b"x" * (ps + 1)])
    assert exc.value.status_code == 400
    assert uploads.received_bytes("u1", uid) == 0


def test_more_bytes_than_declared_at_init_is_refused():
    ps = uploads.part_size()
    uid = uploads.create_session("u1", "talk.mp4", ps, _plan())["upload_id"]
    with pytest.raises(HTTPException) as exc:
        _append("u1", uid, 0, [b"x" * ps, b"y" * 10])
    assert exc.value.status_code == 400
    assert uploads.received_bytes("u1", uid) == 0


def test_complete_refuses_a_short_upload():
    ps = uploads.part_size()
    uid = uploads.create_session("u1", "talk.mp4", 2 * ps, _plan())["upload_id"]
    _append("u1", uid, 0, [b"a" * ps])

    with pytest.raises(HTTPException) as exc:
        uploads.complete_session("u1", uid, _plan())
    assert exc.value.status_code == 409
    assert _detail(exc)["error"] == "incomplete"


def test_complete_moves_the_file_into_the_library_and_clears_staging():
    ps = uploads.part_size()
    uid = uploads.create_session("u1", "talk.mp4", ps, _plan())["upload_id"]
    _append("u1", uid, 0, [b"a" * ps])

    dest, info = uploads.complete_session("u1", uid, _plan())
    assert dest.parent == staging_path() / "videos" / "u1"
    assert dest.suffix == ".mp4"
    assert dest.stat().st_size == ps
    assert info["filename"] == "talk.mp4"
    # staging tree is gone, so a retried complete cannot double-insert
    assert not uploads.session_dir("u1", uid).exists()


def staging_path():
    from pathlib import Path
    return Path(settings.media_root)


def test_another_account_cannot_touch_a_session():
    uid = uploads.create_session("u1", "talk.mp4", 1024, _plan())["upload_id"]
    for call in (
        lambda: uploads.read_meta("u2", uid),
        lambda: _append("u2", uid, 0, [b"x"]),
        lambda: uploads.abort_session("u2", uid),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404


def test_unknown_and_malformed_ids_are_404():
    with pytest.raises(HTTPException) as exc:
        uploads.read_meta("u1", "not-a-uuid")
    assert exc.value.status_code == 404


def test_sweep_removes_only_abandoned_sessions():
    old = uploads.create_session("u1", "old.mp4", 1024, _plan())["upload_id"]
    fresh = uploads.create_session("u1", "new.mp4", 1024, _plan())["upload_id"]

    d = uploads.session_dir("u1", old)
    stale = time.time() - 48 * 3600
    os.utime(d, (stale, stale))

    assert uploads.sweep_stale() == 1
    assert not d.exists()
    assert uploads.session_dir("u1", fresh).exists()


def test_meta_records_the_plan_the_upload_started_under():
    uid = uploads.create_session("u1", "talk.mp4", 1024, _plan(name="free"))["upload_id"]
    meta = json.loads((uploads.session_dir("u1", uid) / "meta.json").read_text())
    assert meta["plan"] == "free"
    assert meta["user_id"] == "u1"
