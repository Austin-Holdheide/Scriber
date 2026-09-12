import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase, api } from "../lib/supabase";
import type { VideoRow } from "../lib/types";

const stageLabel: Record<string, string> = {
  queued: "queued", extracting: "extracting audio",
  transcribing: "transcribing", writing: "writing", done: "done", failed: "failed",
};

export default function Videos() {
  const [videos, setVideos] = useState<VideoRow[]>([]);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState<{ name: string; pct: number } | null>(null);
  const [err, setErr] = useState("");
  const [pendingDel, setPendingDel] = useState<VideoRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const refresh = useCallback(async () => {
    try {
      const res = await api("/videos");
      setVideos(await res.json());
    } catch (e: any) { setErr(e.message); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // LIVE STATUS: subscribe to jobs table changes (Realtime)
  useEffect(() => {
    const channel = supabase
      .channel("jobs-live")
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "jobs" },
        (payload: any) => {
          const j = payload.new;
          setVideos((prev) =>
            prev.map((v) =>
              v.id === j.video_id ? { ...v, stage: j.stage, progress: j.progress, status: j.stage === "done" ? "done" : j.stage === "failed" ? "failed" : "working" } : v
            )
          );
        })
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, []);

  const upload = (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setErr("");
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    supabase.auth.getSession().then(({ data }) => {
      xhr.open("POST", "/api/videos/upload");
      xhr.setRequestHeader("Authorization", `Bearer ${data.session?.access_token}`);
      xhr.upload.onprogress = (ev) =>
        ev.lengthComputable && setUploading({ name: file.name, pct: Math.round((ev.loaded / ev.total) * 100) });
      xhr.onload = () => {
        setUploading(null);
        if (xhr.status === 201) refresh();
        else setErr(`upload failed: ${xhr.status} ${xhr.responseText.slice(0, 120)}`);
      };
      xhr.onerror = () => { setUploading(null); setErr("network error"); };
      xhr.send(form);
    });
  };

  const state = (v: VideoRow) => {
    const st = v.stage || v.status;
    if (st === "done") return <span className="badge done">done</span>;
    if (st === "failed") return <span className="badge failed">failed</span>;
    if (["queued", "extracting", "transcribing", "writing"].includes(st))
      return (
        <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span className="badge working">{stageLabel[st] || st}</span>
          <span className="progressbar"><div style={{ width: `${v.progress ?? 0}%` }} /></span>
        </span>
      );
    return <span className="badge working">{st}</span>;
  };

  const confirmDel = async () => {
    if (!pendingDel) return;
    setDeleting(true);
    try {
      await api(`/videos/${pendingDel.id}`, { method: "DELETE" });
      setVideos((prev) => prev.filter((x) => x.id !== pendingDel.id));
      setPendingDel(null);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <div
        className={`drop ${drag ? "hot" : ""}`}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}
      >
        {uploading
          ? `uploading ${uploading.name} — ${uploading.pct}%`
          : "drag & drop a video/audio file — or click to browse"}
        <input ref={fileRef} type="file" hidden
          accept=".mp4,.mkv,.avi,.mov,.webm,.mp3,.wav,.m4a,.flac,.ogg,.opus"
          onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
      </div>
      {err && <p className="muted" style={{ color: "#f87171" }}>{err}</p>}

      {videos.map((v) => (
        <div key={v.id} className="card" style={{ cursor: "pointer" }}
             onClick={() => navigate(`/videos/${v.id}`)}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {v.filename}
            </div>
            <div className="muted">
              {v.language ? `${v.language} · ` : ""}
              {v.size_bytes ? `${(v.size_bytes / 1048576).toFixed(1)}MB · ` : ""}
              {new Date(v.created_at).toLocaleString()}
            </div>
          </div>
          <span className="state-cell">{state(v)}</span>
          <button className="ghost del" title="delete" onClick={(e) => { e.stopPropagation(); setPendingDel(v); }}>✕</button>
        </div>
      ))}
      {videos.length === 0 && <p className="muted" style={{ textAlign: "center" }}>no videos yet — drop one above</p>}

      {pendingDel && (
        <div className="modal-backdrop" onClick={() => !deleting && setPendingDel(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Delete video?</h3>
            <p style={{ fontWeight: 600, margin: "0.5rem 0" }}>{pendingDel.filename}</p>
            <p className="muted">
              This permanently removes the original file, the transcript, and all segments. There is no undo.
            </p>
            <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "1rem" }}>
              <button className="ghost" disabled={deleting} onClick={() => setPendingDel(null)}>cancel</button>
              <button className="danger" disabled={deleting} onClick={confirmDel}>
                {deleting ? "deleting…" : "delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
