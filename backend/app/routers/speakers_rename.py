"""W10: bulk speaker rename - map generic labels to real names for one video."""
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.supabase_client import admin_client
from app.services.auth import get_current_user

router = APIRouter()


class RenameBody(BaseModel):
    mapping: dict[str, str]  # {"Speaker 1": "Linus", "Speaker 2": "Wendell"}


@router.post("/{video_id}/speakers")
def rename_speakers(video_id: str, body: RenameBody, user_id: str = Depends(get_current_user)):
    """Rename speakers across all segments of this video's transcript.
    mapping: {oldLabel: newLabel}. Empty newLabel = clear the speaker on those segments."""
    try:
        _uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(404, "not found")

    v = (admin_client().table("videos")
         .select("id").eq("id", video_id).eq("user_id", user_id).limit(1).execute())
    if not v.data:
        raise HTTPException(404, "not found")

    t = (admin_client().table("transcripts")
         .select("id, speakers").eq("video_id", video_id)
         .order("created_at", desc=True).limit(1).execute())
    if not t.data:
        raise HTTPException(404, "no transcript")
    transcript_id = t.data[0]["id"]

    clean = {k.strip(): v.strip() for k, v in body.mapping.items() if k.strip()}
    if not clean:
        raise HTTPException(422, "empty mapping")

    total = 0
    for old_label, new_label in clean.items():
        offset, page = 0, 1000
        while True:
            r = (admin_client().table("segments")
                 .select("id").eq("transcript_id", transcript_id)
                 .eq("speaker", old_label)
                 .range(offset, offset + page - 1).execute())
            rows = r.data
            if not rows:
                break
            # update by chunk of explicit ids (PostgREST lacks bulk-diff update)
            for i in range(0, len(rows), 200):
                ids = [r["id"] for r in rows[i:i + 200]]
                admin_client().table("segments").update(
                    {"speaker": new_label or None}
                ).in_("id", ids).execute()
            total += len(rows)
            if len(rows) < page:
                break
            offset += page

    # persist mapping on the transcript (merge over existing)
    stored = t.data[0].get("speakers") or {}
    # translate any stored raw keys through the same mapping for consistency
    stored_out = {}
    for raw, human in stored.items():
        new_human = clean.get(human, human)
        stored_out[raw] = new_human
    for old_label, new_label in clean.items():
        if old_label not in stored_out.values():
            stored_out[old_label] = new_label
    # keep rank order in sync with renames
    order = t.data[0].get("speaker_order") or []
    order_out = [clean.get(h, h) for h in order]
    admin_client().table("transcripts").update({
        "speakers": stored_out,
        "speaker_order": order_out,
    }).eq("id", transcript_id).execute()

    return {"renamed": total, "mapping": clean}
