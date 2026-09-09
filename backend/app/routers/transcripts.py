"""Transcript + artifact endpoints (W7)."""
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response

from app.config import settings
from app.services.supabase_client import admin_client
from app.services.auth import get_current_user

router = APIRouter()


def _get_video(video_id: str, user_id: str):
    import uuid as _uuid
    try:
        _uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(404, "not found")
    r = (admin_client().table("videos")
         .select("id, filename, storage_path, user_id")
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
    segs = (admin_client().table("segments")
            .select("start_ms,end_ms,speaker,text,confidence")
            .eq("transcript_id", t["id"])
            .order("start_ms").execute())
    return JSONResponse({
        "video": {"id": v["id"], "filename": v["filename"]},
        "full_text": t["full_text"],
        "segments": segs.data,
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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
            segs = (admin_client().table("segments")
                    .select("start_ms,speaker,text").eq("transcript_id", t["id"])
                    .order("start_ms").execute())
            export_docx(v, t, segs.data, dest)
        return _stream_file(dest, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"{stem}.docx")
    if kind not in kinds:
        raise HTTPException(400, f"kind must be one of srt/vtt/txt/docx, got {kind}")
    ext, mt = kinds[kind]
    path = Path(settings.media_root) / Path(v["storage_path"]).parent / (stem + ext)
    return _stream_file(path, mt, f"{stem}{ext}")


@router.get("/{video_id}/download")
def download(video_id: str, user_id: str = Depends(get_current_user)):
    v = _get_video(video_id, user_id)
    path = Path(settings.media_root) / v["storage_path"]
    if not path.exists():
        raise HTTPException(404, "file missing")
    return _stream_file(path, "application/octet-stream", v["filename"])

