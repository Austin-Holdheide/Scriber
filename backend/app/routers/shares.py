"""W12: share links — expiring, read-only transcript sharing.

Owner endpoints (JWT):  POST /{video_id}/shares  GET /{video_id}/shares  DELETE /shares/{id}
Public endpoint (no auth, token in URL): GET /public/shares/{token}
"""
import secrets
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.supabase_client import admin_client
from app.services.auth import get_current_user

router = APIRouter()

MAX_TTL_DAYS = 30
DEFAULT_TTL_DAYS = 7


def _own_video(video_id: str, user_id: str) -> dict:
    try:
        _uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(404, "not found")
    r = (admin_client().table("videos")
         .select("id, filename").eq("id", video_id).eq("user_id", user_id).limit(1).execute())
    if not r.data:
        raise HTTPException(404, "not found")
    return r.data[0]


@router.post("/{video_id}/shares")
def create_share(video_id: str, body: dict | None = None, user_id: str = Depends(get_current_user)):
    """Create an expiring share link. body: {"days": 7} (1..30)."""
    v = _own_video(video_id, user_id)
    days = DEFAULT_TTL_DAYS
    if body and isinstance(body.get("days"), int):
        days = max(1, min(body["days"], MAX_TTL_DAYS))

    token = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    r = admin_client().table("share_links").insert({
        "video_id": video_id, "user_id": user_id, "token": token, "expires_at": expires,
    }).execute()
    row = r.data[0]
    return {
        "id": row["id"], "token": token, "expires_at": expires,
        "url": f"/share/{token}",
    }


@router.get("/{video_id}/shares")
def list_shares(video_id: str, user_id: str = Depends(get_current_user)):
    """List my links for this video (active + revoked, with expiry)."""
    _own_video(video_id, user_id)
    now = datetime.utcnow().isoformat()
    r = (admin_client().table("share_links")
         .select("id,token,expires_at,created_at,revoked")
         .eq("video_id", video_id).eq("user_id", user_id)
         .order("created_at", desc=True).execute())
    out = []
    for s in r.data:
        out.append({**s, "expired": s["expires_at"] < now})
    return out


@router.delete("/shares/{share_id}")
def revoke_share(share_id: str, user_id: str = Depends(get_current_user)):
    """Revoke a link (soft delete - token stops working immediately)."""
    try:
        _uuid.UUID(share_id)
    except ValueError:
        raise HTTPException(404, "not found")
    r = (admin_client().table("share_links")
         .select("id").eq("id", share_id).eq("user_id", user_id).limit(1).execute())
    if not r.data:
        raise HTTPException(404, "not found")
    admin_client().table("share_links").update({"revoked": True}).eq("id", share_id).execute()
    return {"revoked": share_id}


# ---------------- PUBLIC (no auth) ----------------

def _load_shared(token: str) -> dict | None:
    now = datetime.utcnow().isoformat()
    r = (admin_client().table("share_links")
         .select("id,video_id,expires_at,revoked")
         .eq("token", token).limit(1).execute())
    if not r.data:
        return None
    s = r.data[0]
    if s["revoked"] or s["expires_at"] < now:
        return None
    return s


MEDIA_TYPES = {
    ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
    ".mov": "video/quicktime", ".webm": "video/webm",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/opus",
}


@router.get("/public/{token}/artifact/{kind}")
def public_share_artifact(token: str, kind: str):
    """Public transcript artifacts for a valid share link (srt / docx / pdf)."""
    from fastapi.responses import FileResponse, Response as _Response
    from app.config import settings as _settings

    s = _load_shared(token)
    if not s:
        raise HTTPException(404, "share link is invalid, expired, or revoked")
    vid = s["video_id"]
    v = (admin_client().table("videos")
         .select("filename, storage_path").eq("id", vid).limit(1).execute())
    if not v.data:
        raise HTTPException(404, "not found")
    t = (admin_client().table("transcripts")
         .select("id, full_text, model").eq("video_id", vid).limit(1).execute())
    if not t.data:
        raise HTTPException(404, "no transcript yet")

    stem = Path(v.data[0]["storage_path"]).stem
    fname = v.data[0]["filename"]
    ascii_base = fname.encode("ascii", "replace").decode().replace('"', "")
    base_noext = ascii_base.rsplit(".", 1)[0] or "transcript"

    if kind == "txt":
        # on-the-fly plain text
        return _Response(
            content=(t.data[0]["full_text"] or ""),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{base_noext}.txt"'},
        )
    if kind == "srt":
        path = Path(_settings.media_root) / Path(v.data[0]["storage_path"]).parent / (stem + ".srt")
        if not path.exists():
            raise HTTPException(404, "artifact missing")
        return FileResponse(path, media_type="application/x-subrip",
                            headers={"Content-Disposition": f'attachment; filename="{base_noext}.srt"'})
    if kind == "docx":
        path = Path(_settings.media_root) / Path(v.data[0]["storage_path"]).parent / (stem + ".docx")
        if not path.exists():
            from app.services.docx_export import export_docx
            # paged segments (cap defense)
            segs, offset, page = [], 0, 1000
            while True:
                r = (admin_client().table("segments")
                     .select("start_ms,speaker,text").eq("transcript_id", t.data[0]["id"])
                     .order("start_ms").range(offset, offset + page - 1).execute())
                segs.extend(r.data)
                if len(r.data) < page:
                    break
                offset += page
            export_docx(v.data[0], t.data[0], segs, path)
        return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            headers={"Content-Disposition": f'attachment; filename="{base_noext}.docx"'})
    if kind == "pdf":
        path = Path(_settings.media_root) / Path(v.data[0]["storage_path"]).parent / (stem + ".pdf")
        if not path.exists():
            from app.services.pdf_export import export_pdf
            segs, offset, page = [], 0, 1000
            while True:
                r = (admin_client().table("segments")
                     .select("start_ms,speaker,text").eq("transcript_id", t.data[0]["id"])
                     .order("start_ms").range(offset, offset + page - 1).execute())
                segs.extend(r.data)
                if len(r.data) < page:
                    break
                offset += page
            export_pdf(v.data[0], t.data[0], segs, path)
        return FileResponse(path, media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{base_noext}.pdf"'})
    raise HTTPException(400, "kind must be one of srt/docx/pdf/txt")


@router.get("/public/{token}/thumb")
def public_share_thumb(token: str):
    """Public poster frame for a valid share link (video files only)."""
    from fastapi.responses import FileResponse
    from app.config import settings as _settings

    s = _load_shared(token)
    if not s:
        raise HTTPException(404, "share link is invalid, expired, or revoked")
    v = (admin_client().table("videos")
         .select("storage_path").eq("id", s["video_id"]).limit(1).execute())
    if not v.data:
        raise HTTPException(404, "not found")
    src = Path(_settings.media_root) / v.data[0]["storage_path"]
    thumb = src.parent / f"{src.stem}.thumb.jpg"
    if not thumb.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(thumb, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=600"})


@router.get("/public/{token}/media")
def public_share_media(token: str):
    """Public media stream for a valid share link (share token = authorization).
    FileResponse serves Range requests, so seeking works."""
    from fastapi.responses import FileResponse
    from app.config import settings as _settings

    s = _load_shared(token)
    if not s:
        raise HTTPException(404, "share link is invalid, expired, or revoked")
    v = (admin_client().table("videos")
         .select("filename, storage_path").eq("id", s["video_id"]).limit(1).execute())
    if not v.data:
        raise HTTPException(404, "video not found")
    path = Path(_settings.media_root) / v.data[0]["storage_path"]
    if not path.exists():
        raise HTTPException(404, "media file missing")
    mt = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=mt, headers={
        "Content-Disposition": f'inline; filename="{v.data[0]["filename"].encode("ascii", "replace").decode().replace(chr(34), "")}"',
        "Accept-Ranges": "none",  # starlette adds its own range handling
    })


@router.get("/public/{token}")
def public_share(token: str):
    """Public read-only transcript payload for a valid, unexpired link."""
    s = _load_shared(token)
    if not s:
        raise HTTPException(404, "share link is invalid, expired, or revoked")
    vid = s["video_id"]
    v = (admin_client().table("videos")
         .select("filename, language, created_at").eq("id", vid).limit(1).execute())
    if not v.data:
        raise HTTPException(404, "video not found")
    t = (admin_client().table("transcripts")
         .select("full_text, model, created_at").eq("video_id", vid).limit(1).execute())
    # paginate segments (same 1000-row cap defense as transcripts.py)
    seg_rows: list = []
    if t.data:
        t_id = (admin_client().table("transcripts")
                .select("id").eq("video_id", vid).limit(1).execute().data[0]["id"])
        offset, page = 0, 1000
        while True:
            r = (admin_client().table("segments")
                 .select("id,start_ms,end_ms,speaker,text")
                 .eq("transcript_id", t_id).order("start_ms")
                 .range(offset, offset + page - 1).execute())
            seg_rows.extend(r.data)
            if len(r.data) < page:
                break
            offset += page
    vv = v.data[0]
    tt = t.data[0] if t.data else {"full_text": None, "model": None, "created_at": None}
    return {
        "video": {"filename": vv["filename"], "language": vv.get("language")},
        "transcript": {"full_text": tt["full_text"], "model": tt["model"]},
        "segments": seg_rows,
    }
