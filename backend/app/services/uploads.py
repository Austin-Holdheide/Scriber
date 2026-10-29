"""Chunked upload sessions, staged on the media filesystem.

Why this exists: Cloudflare refuses a single request body over 100 MB on Free
and Pro plans, so a 5 GB Pro upload can never arrive as one multipart POST.
Splitting the file into parts smaller than that limit keeps the origin behind
the proxy (no grey-clouded DNS record, no exposed IP, WAF still applies).

Parts are appended in order to one file on disk rather than staged separately
and concatenated: one copy instead of two, and a rename - not a copy - moves it
into `videos/<user_id>/` when the last part lands.

State is the filesystem itself, so there is no table and no migration:

    <media_root>/uploads/<user_id>/<upload_id>/meta.json   filename, ext, size, plan
    <media_root>/uploads/<user_id>/<upload_id>/data.bin    bytes received so far

Resuming is just "how big is data.bin": `next_index = received // part_size`.
"""
import json
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.services import quota

log = logging.getLogger("scriber.uploads")

MB = 1024 * 1024
SESSION_TTL_S = 24 * 3600


def part_size() -> int:
    """Part size in bytes. Must stay well under Cloudflare's 100 MB body cap."""
    try:
        mb = int(os.getenv("UPLOAD_PART_SIZE_MB", "64"))
    except ValueError:
        mb = 64
    return max(1, mb) * MB


def upload_root() -> Path:
    return Path(settings.media_root) / "uploads"


def _valid_id(upload_id: str) -> str:
    try:
        return str(uuid.UUID(upload_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(404, "unknown upload")


def session_dir(user_id: str, upload_id: str) -> Path:
    return upload_root() / user_id / _valid_id(upload_id)


def _meta_path(d: Path) -> Path:
    return d / "meta.json"


def _data_path(d: Path) -> Path:
    return d / "data.bin"


def read_meta(user_id: str, upload_id: str) -> dict:
    d = session_dir(user_id, upload_id)
    try:
        meta = json.loads(_meta_path(d).read_text())
    except FileNotFoundError:
        raise HTTPException(404, "unknown upload")
    except (OSError, ValueError):
        log.exception("unreadable upload session %s", d)
        raise HTTPException(500, "upload session unreadable")
    if meta.get("user_id") != user_id:
        # a session id must never be usable by another account
        raise HTTPException(404, "unknown upload")
    return meta


def received_bytes(user_id: str, upload_id: str) -> int:
    d = session_dir(user_id, upload_id)
    try:
        return _data_path(d).stat().st_size
    except FileNotFoundError:
        return 0


def status(user_id: str, upload_id: str) -> dict:
    meta = read_meta(user_id, upload_id)
    ps = meta["part_size"]
    got = received_bytes(user_id, upload_id)
    return {
        "upload_id": upload_id,
        "filename": meta["filename"],
        "size_bytes": meta["size_bytes"],
        "received_bytes": got,
        "part_size": ps,
        "next_index": got // ps,
    }


def sweep_stale(ttl_s: int = SESSION_TTL_S) -> int:
    """Drop abandoned sessions. Only touches the staging tree, never `videos/`."""
    root = upload_root()
    if not root.is_dir():
        return 0
    cutoff = time.time() - ttl_s
    removed = 0
    try:
        for user_dir in root.iterdir():
            if not user_dir.is_dir():
                continue
            for sess in user_dir.iterdir():
                try:
                    if sess.is_dir() and sess.stat().st_mtime < cutoff:
                        for f in sess.iterdir():
                            f.unlink(missing_ok=True)
                        sess.rmdir()
                        removed += 1
                except OSError:
                    continue
            try:
                if not any(user_dir.iterdir()):
                    user_dir.rmdir()
            except OSError:
                pass
    except OSError:
        log.exception("stale upload sweep failed (non-fatal)")
    if removed:
        log.info("swept %d abandoned upload session(s)", removed)
    return removed


def create_session(user_id: str, filename: str, size_bytes: int, plan: quota.Plan) -> dict:
    upload_id = str(uuid.uuid4())
    d = session_dir(user_id, upload_id)
    d.mkdir(parents=True, exist_ok=False)
    ps = part_size()
    meta = {
        "upload_id": upload_id,
        "user_id": user_id,
        "filename": filename,
        "ext": Path(filename).suffix.lower(),
        "size_bytes": int(size_bytes or 0),
        "part_size": ps,
        "plan": plan.name,
        # pin the cap the account had when it started: parts enforce this, not a
        # fresh lookup, so a mid-upload plan change cannot loosen a running upload
        "max_upload_bytes": plan.max_upload_bytes,
        "created_at": time.time(),
    }
    _meta_path(d).write_text(json.dumps(meta))
    # a zero-length data file makes "received" a real 0 rather than a missing path
    _data_path(d).touch()
    return status(user_id, upload_id) | {"part_size": ps}


def _plan_from_meta(meta: dict) -> quota.Plan:
    return quota.PLANS.get(meta.get("plan", ""), quota.PLANS[quota.DEFAULT_PLAN])


async def _aiter(chunks):
    """Accept either an async iterator (a request stream) or a plain iterable.

    The router hands us `request.stream()`; tests hand us a list of bytes.
    """
    if hasattr(chunks, "__aiter__"):
        async for chunk in chunks:
            yield chunk
    else:
        for chunk in chunks:
            yield chunk


async def append_part(user_id: str, upload_id: str, index: int, chunks) -> dict:
    """Append one part. `chunks` is an async iterator or an iterable of bytes."""
    meta = read_meta(user_id, upload_id)
    d = session_dir(user_id, upload_id)
    ps = meta["part_size"]
    plan = _plan_from_meta(meta)

    got = received_bytes(user_id, upload_id)
    expect = got // ps
    if index != expect:
        # out of order or a duplicate retry: tell the client where to resume
        raise HTTPException(409, {
            "error": "out_of_order",
            "message": f"expected part {expect}, got {index}",
            "next_index": expect,
            "received_bytes": got,
        })

    declared = int(meta.get("size_bytes") or 0)
    cap = int(meta.get("max_upload_bytes", plan.max_upload_bytes))
    written = got
    try:
        with open(_data_path(d), "ab") as out:
            async for chunk in _aiter(chunks):
                if not chunk:
                    continue
                written += len(chunk)
                # 2. same ceiling as the single-shot path, enforced mid-part
                if 0 < cap < written:
                    out.truncate(got)
                    raise quota._too_big(plan, cap, written)
                if declared and written > declared:
                    out.truncate(got)
                    raise HTTPException(400, "more bytes than declared at init")
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    except HTTPException:
        raise
    except OSError:
        log.exception("staging write failed for %s", upload_id)
        raise HTTPException(500, "storage write failed")

    part_len = written - got
    if part_len > ps:
        # keep the client honest so `next_index = received // part_size` stays true
        os.truncate(_data_path(d), got)
        raise HTTPException(400, f"part larger than the advertised {ps} bytes")

    return {
        "upload_id": upload_id,
        "index": index,
        "part_bytes": part_len,
        "received_bytes": written,
        "next_index": written // ps,
    }


def complete_session(user_id: str, upload_id: str, plan: quota.Plan) -> tuple[Path, dict]:
    """Validate the assembled file and move it into the library path."""
    meta = read_meta(user_id, upload_id)
    d = session_dir(user_id, upload_id)
    got = received_bytes(user_id, upload_id)
    declared = int(meta.get("size_bytes") or 0)

    if declared and got != declared:
        raise HTTPException(409, {
            "error": "incomplete",
            "message": f"received {got} of {declared} bytes",
            "received_bytes": got,
            "next_index": got // meta["part_size"],
        })
    if got == 0:
        raise HTTPException(400, "empty upload")

    # re-read the plan here: a downgrade during a long upload must not keep the old cap
    quota.check_size(plan, got)

    ext = meta["ext"]
    vid = str(uuid.uuid4())
    dest_dir = Path(settings.media_root) / "videos" / user_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{vid}{ext}"
    try:
        os.replace(_data_path(d), dest)   # same filesystem: rename, not copy
    except OSError:
        log.exception("could not move staged upload into place")
        raise HTTPException(500, "storage write failed")

    _cleanup(d)
    return dest, {**meta, "vid": vid}


def abort_session(user_id: str, upload_id: str) -> None:
    d = session_dir(user_id, upload_id)
    read_meta(user_id, upload_id)   # 404s an unknown or foreign session
    _cleanup(d)


def _cleanup(d: Path) -> None:
    try:
        for f in d.iterdir():
            f.unlink(missing_ok=True)
        d.rmdir()
    except OSError:
        log.warning("could not fully remove upload session %s", d)
