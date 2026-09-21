import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import type { Segment } from "../lib/types";

const VIDEO_EXT = new Set(["mp4", "mkv", "avi", "mov", "webm"]);

type ShareData = {
  video: { filename: string; language?: string | null };
  transcript: { full_text: string | null; model: string | null };
  segments: Segment[];
};

function fmt(ms: number): string {
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function SharePage() {
  const { token = "" } = useParams();
  const [data, setData] = useState<ShareData | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [hasThumb, setHasThumb] = useState(false);
  const [activeSeg, setActiveSeg] = useState<number | null>(null);
  const [matchesJustCleared, setMatchesJustCleared] = useState<number | null>(null);
  const isDiarized = ((data as any)?.speaker_order ?? []).length > 0;

  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  const segEls = useRef<Map<number, HTMLDivElement>>(new Map());

  // ---- load payload + poster probe ----
  useEffect(() => {
    fetch(`/api/videos/public/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (!r.ok) {
          const b = await r.json().catch(() => ({}));
          throw new Error(typeof b.detail === "string" ? b.detail : `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message));
    fetch(`/api/videos/public/${encodeURIComponent(token)}/thumb`)
      .then((r) => setHasThumb(r.ok))
      .catch(() => {});
  }, [token]);

  const isVideo = useMemo(() => {
    if (!data) return false;
    const ext = data.video.filename.split(".").pop()?.toLowerCase() ?? "";
    return VIDEO_EXT.has(ext);
  }, [data]);

  // ---- synced highlight: same rAF pattern as VideoPage ----
  useEffect(() => {
    if (!data) return;
    let raf = 0;
    let lastActive: number | null = null;
    const tick = () => {
      const el = mediaRef.current;
      if (el && !el.paused) {
        const t = el.currentTime * 1000;
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
          setActiveSeg(active);
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

  const dl = (kind: string, spk?: "real" | "generic") => {
    const qs = kind !== "video" && spk === "generic" ? "?spk=generic" : "";
    const url = kind === "video"
      ? `/api/videos/public/${encodeURIComponent(token)}/media`
      : `/api/videos/public/${encodeURIComponent(token)}/artifact/${kind}${qs}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = kind === "video" ? (data?.video.filename || "media") : `${(data?.video.filename || "transcript").replace(/\.[^.]+$/, "")}${spk === "generic" ? "-generic" : ""}.${kind}`;
    a.click();
  };

  // after clearing a search by clicking a match, scroll the full list to that segment
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

  // ---- search filter ----
  const matches = useMemo(() => {
    if (!query.trim() || !data) return null;
    const q = query.toLowerCase();
    return new Set(data.segments.filter((s) => s.text.toLowerCase().includes(q)).map((s) => s.id));
  }, [query, data]);

  if (error) {
    return (
      <div className="container" style={{ textAlign: "center", paddingTop: "4rem" }}>
        <h1 style={{ fontSize: "1.6rem" }}>🔒 Link unavailable</h1>
        <p className="muted">{error}</p>
      </div>
    );
  }
  if (!data) return <div className="container muted">loading…</div>;

  return (
    <div className="container wide share-page">
      <p className="muted" style={{ marginBottom: 0 }}>shared transcript · read-only</p>
      <h2 style={{ margin: "0.25rem 0 1rem" }}>{data.video.filename}</h2>

      <div className="player-grid">
        <div className="media-pane">
          {isVideo ? (
            <video
              ref={mediaRef as any}
              controls playsInline preload="metadata"
              poster={hasThumb ? `/api/videos/public/${encodeURIComponent(token)}/thumb` : undefined}
              src={`/api/videos/public/${encodeURIComponent(token)}/media`}
              style={{ width: "100%", borderRadius: 8, background: "#000" }}
            />
          ) : (
            <audio
              ref={mediaRef as any}
              controls preload="metadata"
              src={`/api/videos/public/${encodeURIComponent(token)}/media`}
              style={{ width: "100%" }}
            />
          )}
          <div className="muted" style={{ marginTop: "0.5rem" }}>
            {data.segments.length} segments · {data.video.language || "?"} · click a segment to jump
          </div>
          <div className="share-dl-list">
            <span className="muted">downloads:</span>
            {["srt", "docx", "pdf", "video"].map((k) => (
              <button key={k} className="ghost sm" onClick={() => dl(k)}>
                ↓ {k === "video" ? (isVideo ? "original video" : "original audio") : k.toUpperCase()}
              </button>
            ))}
            {isDiarized && ["srt", "docx", "pdf"].map((k) => (
              <button key={k + "-generic"} className="ghost sm" onClick={() => dl(k, "generic")}>
                ↓ {k.toUpperCase()} · Speaker 1/2/3
              </button>
            ))}
          </div>
        </div>

        <div className="segments-pane">
          <div className="searchbar">
            <input
              placeholder="search in transcript…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
          </div>
          <div className="segment-list">
            {data.segments
              .filter((s) => !matches || matches.has(s.id))
              .map((s) => (
                <div
                  key={s.id}
                  ref={(el) => { if (el) segEls.current.set(s.id, el); else segEls.current.delete(s.id); }}
                  className={["segment", activeSeg === s.id ? "active" : "", matches ? "match" : ""].join(" ")}
                  onClick={() => {
                    seekTo(s.start_ms);
                    if (matches) { setQuery(""); setMatchesJustCleared(s.id); }
                  }}
                >
                  <span className="ts">{fmt(s.start_ms)}</span>
                  {s.speaker && <span className="speaker">{s.speaker}</span>}
                  <span className="text">{s.text}</span>
                </div>
              ))}
            {matches && matches.size === 0 && (
              <div className="muted" style={{ padding: "1rem", textAlign: "center" }}>no matches</div>
            )}
          </div>
        </div>
      </div>

      <p className="muted" style={{ textAlign: "center", marginTop: "1rem" }}>shared via Scribly</p>
    </div>
  );
}
