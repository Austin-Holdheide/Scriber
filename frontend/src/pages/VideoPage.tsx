import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, supabase } from "../lib/supabase";
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

  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const segEls = useRef<Map<number, HTMLDivElement>>(new Map());

  // ---- load transcript ----
  useEffect(() => {
    setData(null); setError(""); setActiveSeg(null); setMediaSrc(null);
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

  if (error) {
    return (
      <div className="container">
        <Link to="/" className="muted">← back</Link>
        <p style={{ color: "#f87171" }}>{error}</p>
      </div>
    );
  }
  if (!data || !mediaSrc) return <div className="container muted">loading…</div>;

  const vttSrc = `/api/videos/${videoId}/artifacts/vtt`;

  return (
    <div className="container wide">
      <Link to="/" className="muted">← all videos</Link>
      <h2 style={{ margin: "0.75rem 0 1rem" }}>{data.video.filename}</h2>

      <div className="player-grid">
        <div className="media-pane">
          {isVideo ? (
            <video ref={mediaRef as any} src={mediaSrc ?? undefined} controls playsInline style={{ width: "100%", borderRadius: 8, background: "#000" }}>
              <track kind="subtitles" src={vttSrc} srcLang="en" default={false} />
            </video>
          ) : (
            <audio ref={mediaRef as any} src={mediaSrc ?? undefined} controls style={{ width: "100%" }} />
          )}
          <div className="exportrow" style={{ marginTop: "0.6rem" }}>
            <span className="muted">download:</span>
            {["srt", "vtt", "txt", "docx", "video"].map((k) => (
              <button key={k} className="ghost" onClick={() => dl(k)}>{k}</button>
            ))}
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
          </div>

          <div className="segment-list" ref={listRef}>
            {data.segments.map((s) => {
              const isActive = activeSeg === s.id;
              const isMatch = matches?.has(s.id);
              const dimmed = matches && !isMatch;
              return (
                <div
                  key={s.id}
                  ref={(el) => { if (el) segEls.current.set(s.id, el); else segEls.current.delete(s.id); }}
                  className={[
                    "segment",
                    isActive ? "active" : "",
                    isMatch ? "match" : "",
                    dimmed ? "dimmed" : "",
                  ].join(" ")}
                  onClick={() => seekTo(s.start_ms)}
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
          </div>


        </div>
      </div>
    </div>
  );
}
