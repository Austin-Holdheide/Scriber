"""Chunked upload endpoints - for files a proxy will not accept in one request.

Flow:
    POST   /api/videos/upload/init                  {filename, size_bytes} -> upload_id, part_size
    PUT    /api/videos/upload/{id}/part/{index}     raw bytes, in order
    GET    /api/videos/upload/{id}                  resume: next_index, received_bytes
    POST   /api/videos/upload/{id}/complete         assemble -> same ingest path as single-shot
    DELETE /api/videos/upload/{id}                  abort and free the staging bytes

Enforcement order is unchanged from the single-shot endpoint:
  1. at init        - plan lookup + rolling allowance (429), declared size (413)
  2. per part       - the byte cap, aborted mid-part (413)
  3. at complete    - ffprobe duration against the length cap (422)
A refused upload leaves no video row, no job, no usage event and no staged bytes.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import quota, uploads
from app.services.auth import get_current_user
from app.services.ingest import finalize_upload
from app.routers.videos import ALLOWED_EXT

log = logging.getLogger("scriber.uploads")
router = APIRouter()


class InitBody(BaseModel):
    filename: str
    size_bytes: int = 0


@router.post("/upload/init")
async def init_upload(body: InitBody, user_id: str = Depends(get_current_user)):
    ext = Path(body.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"unsupported file type {ext!r}")

    # 1. allowance first, then the declared size - both before a byte is stored
    plan = quota.check_transcription(user_id)
    if body.size_bytes:
        quota.check_size(plan, body.size_bytes)

    uploads.sweep_stale()
    session = uploads.create_session(user_id, body.filename, body.size_bytes, plan)
    return JSONResponse(status_code=201, content={
        **session, "plan": plan.name,
        "max_upload_bytes": plan.max_upload_bytes,
    })


@router.get("/upload/{upload_id}")
async def upload_status(upload_id: str, user_id: str = Depends(get_current_user)):
    return uploads.status(user_id, upload_id)


async def _body_chunks(request: Request):
    async for chunk in request.stream():
        yield chunk


@router.put("/upload/{upload_id}/part/{index}")
async def put_part(upload_id: str, index: int, request: Request,
                   user_id: str = Depends(get_current_user)):
    # reject an oversized part before reading it, when the client declares a length
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > uploads.part_size():
                raise HTTPException(400, f"part larger than the advertised {uploads.part_size()} bytes")
        except ValueError:
            raise HTTPException(400, "bad content-length")

    result = await uploads.append_part(user_id, upload_id, index, _body_chunks(request))
    return result


@router.post("/upload/{upload_id}/complete")
async def complete_upload(upload_id: str, user_id: str = Depends(get_current_user)):
    meta = uploads.read_meta(user_id, upload_id)
    # fresh lookup: a plan change during a long upload must be honoured here
    plan = quota.plan_for(user_id)
    dest, info = uploads.complete_session(user_id, upload_id, plan)
    body = finalize_upload(user_id=user_id, dest=dest, filename=info["filename"],
                           ext=info["ext"], plan=plan, vid=info["vid"])
    return JSONResponse(status_code=201, content=body)


@router.delete("/upload/{upload_id}")
async def abort_upload(upload_id: str, user_id: str = Depends(get_current_user)):
    uploads.abort_session(user_id, upload_id)
    return {"upload_id": upload_id, "aborted": True}
