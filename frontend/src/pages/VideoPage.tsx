import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, supabase } from "../lib/supabase";
import ShareModal from "../components/ShareModal";
import SpeakerRename from "../components/SpeakerRename";
import { copyText } from "../lib/clipboard";
import type { Segment, TranscriptData } from "../lib/types";

const VIDEO_EXT = new Set(["mp4", "mkv", "avi", "mov", "webm"]);
const AUDIO_EXT = new Set(["mp3", "wav", "m4a", "flac", "ogg", "opus"]);

function fmt(ms: number, withMs = false): string {
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const ms2 = ms % 1000;
  const core = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return withMs ? `${core}.${String(ms2).padStart(3, "0")}` : core;
}

export default function VideoPage() {
  const { videoId = "" } = useParams();
  const [data, setData] = useState<TranscriptData | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [saving, setSaving] = useState(false);
  const [activeSeg, setActiveSeg] = useState<number | null>(null);
  const [mediaSrc, setMediaSrc] = useState<string | null>(null);
  const [posterSrc, setPosterSrc] = useState<string | null>(null);
  const [job, setJob] = useState<{ stage: string; progress: number; error?: string | null } | null>(null);
  const [jobBusy, setJobBusy] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [confirmWhat, setConfirmWhat] = useState<"delete" | "retranscribe" | "diarize" | null>(null);
  const [copied, setCopied] = useState(false);
  const [matchesJustCleared, setMatchesJustCleared] = useState<number | null>(null);
  const navigate = useNavigate();

  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const segEls = useRef<Map<number, HTMLDivElement>>(new Map());

  // ---- load transcript ----
  useEffect(() => {
    setData(null); setError(""); setActiveSeg(null); setMediaSrc(null); setPosterSrc(null);
    api(`/videos/${videoId}/transcript`)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(e.message));
    // <audio>/<video> elements cannot send Authorization headers -> signed query token
    api(`/videos/${videoId}/media-token`)
      .then((r) => r.json())
      .then(async ({ token }) => {
        const { data: u } = await supabase.auth.getUser();
        const uid = u.user?.id ?? "";
        setMediaSrc(`/api/videos/${videoId}/download?mt=${encodeURIComponent(token)}&mu=${encodeURIComponent(uid)}`);
      })
      .catch((e) => setError(e.message));
  }, [videoId]);

  // ---- job status + poster thumbnail ----
  const loadJob = useCallback(() => {
    api(`/videos/${videoId}`)
      .then((r) => r.json())
      .then((v) => {
        setJob({ stage: v.stage || v.status, progress: v.progress ?? 0, error: v.error ?? null });
        if (!v.has_thumb) return setPosterSrc(null);
        return Promise.all([
          api(`/videos/${videoId}/media-token`).then((r) => r.json()),
          supabase.auth.getUser(),
        ]).then(([{ token }, { data: u }]) => {
          const uid = u.user?.id ?? "";
          setPosterSrc(`/api/videos/${videoId}/thumbnail?mt=${encodeURIComponent(token)}&mu=${encodeURIComponent(uid)}`);
        });
      })
      .catch(() => {});
  }, [videoId]);

  useEffect(() => { loadJob(); }, [loadJob]);

  // live job updates while on this page (Realtime)
  useEffect(() => {
    const channel = supabase
      .channel(`job-live-${videoId}`)
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "jobs" },
        (payload: any) => {
          const j = payload.new;
          if (j.video_id !== videoId) return;
          setJob({ stage: j.stage, progress: j.progress, error: null });
          if (j.stage === "done" || j.stage === "failed") loadJob(); // refresh transcript link + poster
        })
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [videoId, loadJob]);

  const isVideo = useMemo(() => {
    if (!data) return false;
    const ext = data.video.filename.split(".").pop()?.toLowerCase() ?? "";
    return VIDEO_EXT.has(ext);
  }, [data]);

  // deep-link: /videos/:id?t=<ms> -> seek once media is ready
  const [params] = useSearchParams();
  const seekOnLoad = useRef(true);
  useEffect(() => {
    if (!data || !mediaSrc) return;
    const t = parseInt(params.get("t") ?? "", 10);
    if (seekOnLoad.current && !isNaN(t) && t > 0) {
      seekOnLoad.current = false;
      // wait for metadata
      const el = mediaRef.current;
      const doSeek = () => { el!.currentTime = t / 1000; };
      if (el && el.readyState >= 1) doSeek();
      else el?.addEventListener("loadedmetadata", doSeek, { once: true });
    }
  }, [data, mediaSrc, params]);

  // ---- synced highlight: rAF loop, no react re-render storms ----
  useEffect(() => {
    if (!data) return;
    let raf = 0;
    let lastActive: number | null = null;
    const tick = () => {
      const el = mediaRef.current;
      if (el && !el.paused) {
        const t = el.currentTime * 1000;
        // binary search segments (sorted by start_ms)
        const segs = data.segments;
        let lo = 0, hi = segs.length - 1, found = -1;
        while (lo <= hi) {
          const mid = (lo + hi) >> 1;
          const s = segs[mid];
          if (t < s.start_ms) hi = mid - 1;
          else if (t > s.end_ms) lo = mid + 1;
          else { found = mid; break; }
        }
        const active = found >= 0 ? segs[found].id : null;
        if (active !== lastActive) {
          lastActive = active;
          setActiveSeg(active); // state change only when the active segment actually changes
          if (active != null) {
            segEls.current.get(active)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [data]);

  useEffect(() => {
    if (matchesJustCleared == null || !data) return;
    const t = setTimeout(() => {
      const el = segEls.current.get(matchesJustCleared);
      el?.scrollIntoView({ block: "center", behavior: "smooth" });
      setActiveSeg(matchesJustCleared);
      setMatchesJustCleared(null);
    }, 60);
    return () => clearTimeout(t);
  }, [matchesJustCleared, data]);

  const seekTo = useCallback((ms: number) => {
    const el = mediaRef.current;
    if (el) {
      el.currentTime = ms / 1000;
      el.play();
    }
  }, []);

  // ---- inline edit ----
  const startEdit = (s: Segment) => { setEditingId(s.id); setEditText(s.text); };
  const saveEdit = async (s: Segment) => {
    if (editText === s.text) { setEditingId(null); return; }
    setSaving(true);
    try {
      const res = await api(`/segments/${s.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: editText }),
      });
      const updated = await res.json();
      setData((d) => d && ({
        ...d,
        segments: d.segments.map((x) => (x.id === updated.id ? { ...x, text: updated.text } : x)),
        full_text: d.full_text, // full_text stays as transcript snapshot
      }));
      setEditingId(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  // ---- search filter ----
  const matches = useMemo(() => {
    if (!query.trim()) return null;
    const q = query.toLowerCase();
    return new Set(data?.segments.filter((s) => s.text.toLowerCase().includes(q)).map((s) => s.id));
  }, [query, data]);

  const jumpNext = useCallback(() => {
    if (!data || !matches || matches.size === 0) return;
    const next = data.segments.find((s) => matches.has(s.id) && s.start_ms > (mediaRef.current?.currentTime ?? 0) * 1000)
      ?? data.segments.find((s) => matches.has(s.id)); // wrap
    if (next) seekTo(next.start_ms);
  }, [data, matches, seekTo]);

  // ---- job actions: cancel / retry / re-do ----
  const jobAction = async (kind: "cancel" | "retranscribe" | "diarize") => {
    setJobBusy(true);
    setError("");
    try {
      await api(`/videos/${videoId}/${kind}`, { method: "POST" });
      if (kind === "retranscribe") {
        goHome("Re-transcription queued ✓ — you can watch progress on the video list");
        return;
      }
      loadJob();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setJobBusy(false);
    }
  };

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3200);
  };

  const goHome = (msg: string) => {
    navigate("/");
    // toast lives on window so Videos page renders it right after mount
    (window as any).__scriberToast = msg;
    setTimeout(() => { if ((window as any).__scriberToast === msg) (window as any).__scriberToast = null; }, 4000);
  };

  const deleteVideo = async () => {
    if (deleting) return;
    const name = data?.video.filename || "this video";
    const ok = window.confirm(
      `Delete "${name}"?\n\nThis permanently removes the original file, the transcript, and all segments. There is no undo.`
    );
    if (!ok) return;
    setDeleting(true);
    try {
      await api(`/videos/${videoId}`, { method: "DELETE" });
      setConfirmWhat(null);
      goHome("Video deleted ✓");
    } catch (e: any) {
      setError(e.message);
      setDeleting(false);
    }
  };

  const copyAll = async () => {
    if (!data) return;
    const rows = matches ? data.segments.filter((x) => matches.has(x.id)) : data.segments;
    const text = rows.map((x) => `[${fmt(x.start_ms)}] ${x.text}`).join("\n");
    const ok = await copyText(text);
    setCopied(ok);
    setTimeout(() => setCopied(false), 2000);
  };

  const dl = (kind: string) => {
    const url = kind === "video"
      ? `/videos/${videoId}/download`
      : `/videos/${videoId}/artifacts/${kind}`;
    return api(url)
      .then((r) => r.blob())
      .then((b) => {
        const base = (data?.video.filename || "transcript").replace(/\.[^.]+$/, "");
        const a = document.createElement("a");
        a.href = URL.createObjectURL(b);
        a.download = kind === "video" ? (data?.video.filename || "video") : `${base}.${kind}`;
        a.click();
      });
  };

  if (error && !data) {
    return (
      <div className="container">
        <Link to="/" className="muted">← back</Link>
        <p style={{ color: "#f87171" }}>{error}</p>
      </div>
    );
  }
  if (!data || !mediaSrc) return <div className="container muted">loading…</div>;

  const vttSrc = `/api/videos/${videoId}/artifacts/vtt`;
  const stage = job?.stage ?? "";
  const isActiveJob = ["queued", "extracting", "transcribing", "writing", "diarizing", "cancel_requested"].includes(stage);
  const isDone = stage === "done" || (!isActiveJob && stage !== "failed" && stage !== "cancelled");

  return (
    <div className="container wide">
      <Link to="/" className="muted">← all videos</Link>
      <h2 style={{ margin: "0.75rem 0 1rem" }}>{data.video.filename}</h2>

      {/* JOB STRIP: only shown while a job runs or when it ended badly */}
      {(isActiveJob || stage === "failed" || stage === "cancelled") && (
        <div className="jobstrip">
          {isActiveJob ? (
            <>
              <span className="badge working">{stage === "cancel_requested" ? "cancelling…" : stage}</span>
              <span className="progressbar" style={{ width: 220 }}><div style={{ width: `${job?.progress ?? 0}%` }} /></span>
              <span className="muted">{job?.progress ?? 0}%</span>
              {stage !== "cancel_requested" && (
                <button className="ghost sm stop" disabled={jobBusy} onClick={() => jobAction("cancel")}>■ stop</button>
              )}
            </>
          ) : stage === "failed" ? (
            <>
              <span className="badge failed">failed</span>
              {job?.error && <span className="verror-inline">{job.error}</span>}
            </>
          ) : (
            <span className="badge cancelled">cancelled</span>
          )}
        </div>
      )}
      {error && <p className="muted" style={{ color: "#f87171" }}>{error}</p>}
      {toast && <div className="toast-banner">{toast}</div>}

      <div className="player-grid">
        <div className="media-pane">
          {isVideo ? (
            <video ref={mediaRef as any} src={mediaSrc ?? undefined} poster={posterSrc ?? undefined}
              controls playsInline style={{ width: "100%", borderRadius: 8, background: "#000" }}>
              <track kind="subtitles" src={vttSrc} srcLang="en" default={false} />
            </video>
          ) : (
            <audio ref={mediaRef as any} src={mediaSrc ?? undefined} controls style={{ width: "100%" }} />
          )}
          <div className="video-page-actions">
            <button className="share-big" onClick={() => setShowShare(true)}
              title="Create a read-only share link">🔗 Share</button>
            <div className="menu-wrap">
              <button className="ghost sharebig-ghost" onClick={() => setMenuOpen(!menuOpen)}
                title="More actions">☰</button>
              {menuOpen && (
                <div className="menu-pop" onClick={() => setMenuOpen(false)}>
                  {isDone && (
                    <button className="menu-item" disabled={jobBusy}
                      onClick={() => { setMenuOpen(false); setShowRename(true); }}
                      title="Give speakers real names">
                      ✏️ Rename speakers
                    </button>
                  )}
                  {isDone && (
                    <button className="menu-item" disabled={jobBusy}
                      onClick={() => setConfirmWhat("diarize")}
                      title="Detect speakers and label every segment (runs on GPU - may take a while)">
                      🗣 Detect speakers
                    </button>
                  )}
                  {!isActiveJob && (
                    <button className="menu-item" disabled={jobBusy}
                      onClick={() => setConfirmWhat("retranscribe")}
                      title="Re-run transcription with the current pipeline (replaces this transcript)">
                      {stage === "failed" || stage === "cancelled" ? "↻ Retry transcription" : "↻ Re-transcribe"}
                    </button>
                  )}
                  <div className="menu-sep">danger zone</div>
                  <button className="menu-item danger" disabled={deleting} onClick={() => setConfirmWhat("delete")}>
                    🗑 Delete video
                  </button>
                  <div className="menu-sep">download</div>
                  {["srt", "docx", "pdf", "video"].map((k) => (
                    <button key={k} className="menu-item" onClick={() => dl(k)}>
                      ↓ {k === "video" ? (isVideo ? "original video" : "original audio") : k.toUpperCase()}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="muted" style={{ marginTop: "0.5rem" }}>
            {data.segments.length} segments · {data.video.language || "?"} · click a segment to jump
          </div>
        </div>

        <div className="segments-pane">
          <div className="searchbar">
            <input
              placeholder="search in transcript…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && jumpNext()}
              autoFocus
            />
            {query && (
              <button className="ghost" onClick={jumpNext} title="jump to next match">↓</button>
            )}
            <button className="ghost" onClick={copyAll}
              title={matches ? "Copy the search results" : "Copy all segments"}>
              {copied ? "✓" : matches ? `copy ${matches.size}` : "copy all"}
            </button>
          </div>

          <div className="segment-list" ref={listRef}>
            {data.segments
              .filter((s) => !matches || matches.has(s.id))
              .map((s) => {
              const isActive = activeSeg === s.id;
              const isMatch = matches?.has(s.id);
              return (
                <div
                  key={s.id}
                  ref={(el) => { if (el) segEls.current.set(s.id, el); else segEls.current.delete(s.id); }}
                  className={[
                    "segment",
                    isActive ? "active" : "",
                    isMatch ? "match" : "",
                  ].join(" ")}
                  onClick={() => {
                    seekTo(s.start_ms);
                    if (matches) { setQuery(""); setMatchesJustCleared(s.id); }
                  }}
                >
                  <span className="ts">{fmt(s.start_ms)}</span>
                  {s.speaker && <span className="speaker">{s.speaker}</span>}
                  {editingId === s.id ? (
                    <span className="editbox" onClick={(e) => e.stopPropagation()}>
                      <input
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !saving) saveEdit(s);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        autoFocus
                      />
                      <button disabled={saving} onClick={() => saveEdit(s)}>{saving ? "…" : "save"}</button>
                      <button className="ghost" onClick={() => setEditingId(null)}>esc</button>
                    </span>
                  ) : (
                    <span
                      className="text"
                      onDoubleClick={(e) => { e.stopPropagation(); startEdit(s); }}
                      title="double-click to edit"
                    >
                      {s.text}
                    </span>
                  )}
                </div>
              );
              })}
              {matches && matches.size === 0 && (
                <div className="muted" style={{ padding: "1rem", textAlign: "center" }}>no matches</div>
              )}
          </div>
        </div>
      </div>

      {confirmWhat && (
        <div className="modal-backdrop" onClick={() => !deleting && !jobBusy && setConfirmWhat(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            {confirmWhat === "diarize" ? (
              <>
                <h3>Detect speakers?</h3>
                <p style={{ fontWeight: 600, margin: "0.5rem 0" }}>{data.video.filename}</p>
                <p className="muted">
                  Runs speaker detection on the existing transcript and labels every segment
                  (SPEAKER_1, SPEAKER_2, …). Your video is <b>{Math.round((data.segments[data.segments.length-1]?.end_ms ?? 0) / 60000)} minutes</b> long —
                  this runs on the GPU and <b>can take a while</b> (roughly a quarter of the video's
                  length, so ~{Math.max(1, Math.round((data.segments[data.segments.length-1]?.end_ms ?? 0) / 60000 / 4))} min for this video).
                  You can keep using Scribly; you'll get a notification when it's done.
                </p>
                <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "1rem" }}>
                  <button className="ghost" disabled={jobBusy} onClick={() => setConfirmWhat(null)}>cancel</button>
                  <button disabled={jobBusy} onClick={async () => { setConfirmWhat(null); await jobAction("diarize"); }}>
                    {jobBusy ? "queueing…" : "detect speakers"}
                  </button>
                </div>
              </>
            ) : confirmWhat === "delete" ? (
              <>
                <h3>Delete video?</h3>
                <p style={{ fontWeight: 600, margin: "0.5rem 0" }}>{data.video.filename}</p>
                <p className="muted">
                  This permanently removes the original file, the transcript, and all segments. There is no undo.
                </p>
                <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "1rem" }}>
                  <button className="ghost" disabled={deleting} onClick={() => setConfirmWhat(null)}>cancel</button>
                  <button className="danger" disabled={deleting} onClick={deleteVideo}>
                    {deleting ? "deleting…" : "delete"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3>{stage === "failed" || stage === "cancelled" ? "Retry transcription?" : "Re-transcribe?"}</h3>
                <p style={{ fontWeight: 600, margin: "0.5rem 0" }}>{data.video.filename}</p>
                <p className="muted">
                  The current transcript and all exports (SRT/DOCX/PDF) will be replaced by a fresh run
                  through the current pipeline. This cannot be undone once it starts.
                </p>
                <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "1rem" }}>
                  <button className="ghost" disabled={jobBusy} onClick={() => setConfirmWhat(null)}>cancel</button>
                  <button disabled={jobBusy} onClick={async () => { setConfirmWhat(null); await jobAction("retranscribe"); }}>
                    {jobBusy ? "queueing…" : stage === "failed" || stage === "cancelled" ? "retry" : "re-transcribe"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {showShare && (
        <ShareModal videoId={videoId} filename={data.video.filename} onClose={() => setShowShare(false)} />
      )}
      {showRename && (
        <SpeakerRename videoId={videoId} onClose={() => setShowRename(false)} />
      )}
    </div>
  );
}
