"""Transcript + artifact endpoints (W7)."""
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response

from app.config import settings
from app.services.supabase_client import admin_client
from app.services.auth import get_current_user
from app.services.media_token import issue as issue_media_token, verify as verify_media_token
from app.services.pdf_export import export_pdf


def _all_segments(transcript_id: str) -> list:
    """Paged fetch - PostgREST caps single requests (1000 rows) and silently truncates."""
    all_rows: list = []
    offset, page = 0, 1000
    while True:
        r = (admin_client().table("segments")
             .select("start_ms,speaker,text")
             .eq("transcript_id", transcript_id)
             .order("start_ms")
             .range(offset, offset + page - 1)
             .execute())
        all_rows.extend(r.data)
        if len(r.data) < page:
            break
        offset += page
    return all_rows


router = APIRouter()


def _get_video(video_id: str, user_id: str):
    import uuid as _uuid
    try:
        _uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(404, "not found")
    r = (admin_client().table("videos")
         .select("id, filename, storage_path, user_id, language")
         .eq("id", video_id).eq("user_id", user_id).limit(1).execute())
    if not r.data:
        raise HTTPException(404, "not found")
    return r.data[0]


def _get_transcript(video_id: str):
    r = (admin_client().table("transcripts")
         .select("id, full_text, srt_path, vtt_path, model")
         .eq("video_id", video_id).limit(1).execute())
    if not r.data:
        raise HTTPException(404, "no transcript yet")
    return r.data[0]


@router.get("/{video_id}/transcript")
def transcript(video_id: str, user_id: str = Depends(get_current_user)):
    v = _get_video(video_id, user_id)
    t = _get_transcript(video_id)
    # PostgREST caps a single request at db-max-rows (1000 by default in supabase) and
    # silently truncates. Page through with Range headers so long transcripts are complete.
    all_rows: list = []
    offset = 0
    page = 1000
    while True:
        r = (
            admin_client().table("segments")
            .select("id,start_ms,end_ms,speaker,text,confidence")
            .eq("transcript_id", t["id"])
            .order("start_ms")
            .range(offset, offset + page - 1)
            .execute()
        )
        all_rows.extend(r.data)
        if len(r.data) < page:
            break
        offset += page
    return JSONResponse({
        "video": {"id": v["id"], "filename": v["filename"]},
        "full_text": t["full_text"],
        "segments": all_rows,
    })


def _stream_file(path: Path, media_type: str, filename: str):
    if not path.exists():
        raise HTTPException(404, f"artifact missing on storage: {path.name}")
    def gen():
        with open(path, "rb") as f:
            while chunk := f.read(1024 * 256):
                yield chunk
    return StreamingResponse(
        gen(), media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},  # artifacts stay attachment
    )


@router.get("/{video_id}/artifacts/{kind}")
def artifact(video_id: str, kind: str, user_id: str = Depends(get_current_user)):
    v = _get_video(video_id, user_id)
    t = _get_transcript(video_id)
    stem = Path(v["storage_path"]).stem
    kinds = {
        "srt": (".srt", "application/x-subrip"),
        "vtt": (".vtt", "text/vtt"),
        "txt": (".txt", "text/plain"),
    }
    if kind == "txt":
        # generate plain text on the fly from full_text
        return Response(
            content=(t["full_text"] or ""),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'},
        )
    if kind == "docx":
        from app.services.docx_export import export_docx
        dest = Path(settings.media_root) / Path(v["storage_path"]).parent / (stem + ".docx")
        if not dest.exists():
            export_docx(v, t, _all_segments(t["id"]), dest)
        return _stream_file(dest, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"{stem}.docx")
    if kind == "pdf":
        dest = Path(settings.media_root) / Path(v["storage_path"]).parent / (stem + ".pdf")
        if not dest.exists():
            export_pdf(v, t, _all_segments(t["id"]), dest)
        return _stream_file(dest, "application/pdf", f"{stem}.pdf")
    if kind not in kinds:
        raise HTTPException(400, f"kind must be one of srt/vtt/txt/docx/pdf, got {kind}")
    ext, mt = kinds[kind]
    path = Path(settings.media_root) / Path(v["storage_path"]).parent / (stem + ext)
    return _stream_file(path, mt, f"{stem}{ext}")


MEDIA_TYPES = {
    ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
    ".mov": "video/quicktime", ".webm": "video/webm",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/opus",
}


def _sniff_media_type(path: Path) -> str:
    """True content type from magic bytes (extension lies: jfk.flac renamed .wav etc)."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return "application/octet-stream"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"ID3") or (len(head) > 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    if head.startswith(b"\x1aE\xdf\xa3"):  # EBML = mkv/webm
        return "video/x-matroska"
    if len(head) > 11 and head[4:8] == b"ftyp":
        return "video/mp4"
    # fall back to extension
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


@router.get("/{video_id}/media-token")
def media_token(video_id: str, user_id: str = Depends(get_current_user)):
    """Signed short-lived token for <audio>/<video> src (they can't send headers)."""
    v = _get_video(video_id, user_id)
    return {"token": issue_media_token(video_id, user_id)}


@router.get("/{video_id}/download")
def download(video_id: str, request: Request):
    """Dual auth: `Authorization: Bearer <jwt>` OR signed ?mt= + ?mu= query params
    (media elements cannot send Authorization headers)."""
    import uuid as _uuid

    mt = request.query_params.get("mt", "")
    mu = request.query_params.get("mu", "")
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        user_id = get_current_user(request)
    elif mt and mu:
        if not verify_media_token(video_id, mu, mt):
            raise HTTPException(401, "invalid or expired media token")
        user_id = mu
    else:
        raise HTTPException(401, "missing auth")

    try:
        _uuid.UUID(video_id)
        _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(404, "not found")

    r = (admin_client().table("videos")
         .select("id, filename, storage_path, user_id")
         .eq("id", video_id).eq("user_id", user_id).limit(1).execute())
    if not r.data:
        raise HTTPException(404, "not found")
    v = r.data[0]

    path = Path(settings.media_root) / v["storage_path"]
    if not path.exists():
        raise HTTPException(404, "file missing")
    mt = _sniff_media_type(path)
    # Filenames can contain non-latin1 chars (full-width ？ etc.) - raw headers must be
    # latin-1 encodable. Use RFC 5987: ASCII fallback + filename*=UTF-8 percent-encoded.
    from urllib.parse import quote
    fname = v["filename"]
    ascii_fallback = fname.encode("ascii", "replace").decode().replace('"', "")
    utf8_name = quote(fname)
    return FileResponse(
        path, media_type=mt,
        headers={"Content-Disposition": f"inline; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_name}"},
    )

