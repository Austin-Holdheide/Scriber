import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/supabase";

type Hit = {
  video_id: string;
  filename: string;
  start_ms: number;
  end_ms: number;
  text: string;
  headline: string;
};

function fmt(ms: number): string {
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const navigate = useNavigate();
  const timer = useRef<number | undefined>(undefined);

  const run = useCallback(async (query: string) => {
    if (!query.trim()) { setHits(null); return; }
    setBusy(true); setErr("");
    try {
      const res = await api(`/search?q=${encodeURIComponent(query)}`);
      const body = await res.json();
      setHits(body.results);
    } catch (e: any) {
      setErr(e.message);
      setHits([]);
    } finally {
      setBusy(false);
    }
  }, []);

  // debounced live search
  const onChange = (v: string) => {
    setQ(v);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => run(v), 300);
  };

  useEffect(() => () => window.clearTimeout(timer.current), []);

  return (
    <div style={{ maxWidth: 820, margin: "0 auto" }}>
      <h2>Search transcripts</h2>
      <div className="searchbar" style={{ marginBottom: "1rem" }}>
        <input
          placeholder="search across all your transcripts…"
          value={q}
          onChange={(e) => onChange(e.target.value)}
          autoFocus
        />
      </div>

      {busy && <p className="muted">searching…</p>}
      {err && <p className="muted" style={{ color: "#f87171" }}>{err}</p>}
      {hits !== null && !busy && (
        <p className="muted">{hits.length} result{hits.length === 1 ? "" : "s"}{q && ` for “${q}”`}</p>
      )}

      {hits?.map((h, i) => (
        <div
          key={`${h.video_id}-${h.start_ms}-${i}`}
          className="card"
          style={{ cursor: "pointer", flexDirection: "column", alignItems: "flex-start", gap: "0.3rem" }}
          onClick={() => navigate(`/videos/${h.video_id}?t=${h.start_ms}`)}
        >
          <div style={{ width: "100%", display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
            <span style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {h.filename}
            </span>
            <span className="muted" style={{ fontFamily: "ui-monospace, monospace", flexShrink: 0 }}>
              {fmt(h.start_ms)}
            </span>
          </div>
          <div
            className="muted"
            style={{ lineHeight: 1.4 }}
            // headline is DB-generated with <b> tags; escape everything else
            dangerouslySetInnerHTML={{ __html: htmlEscape(h.headline) }}
          />
        </div>
      ))}
      {hits?.length === 0 && !busy && <p className="muted" style={{ textAlign: "center" }}>nothing found</p>}
    </div>
  );
}

function htmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/&lt;b&gt;/g, "<b>")
    .replace(/&lt;\/b&gt;/g, "</b>");
}
