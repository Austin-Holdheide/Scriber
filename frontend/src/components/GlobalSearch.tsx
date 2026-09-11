import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
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

type GSearchState = {
  q: string;
  setQ: (v: string) => void;
  hits: Hit[] | null;   // null = idle/no query; [] = no results
  busy: boolean;
  err: string;
};

const Ctx = createContext<GSearchState>({ q: "", setQ: () => {}, hits: null, busy: false, err: "" });
export const useGlobalSearch = () => useContext(Ctx);

function htmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/&lt;b&gt;/g, "<b>")
    .replace(/&lt;\/b&gt;/g, "</b>");
}

function fmt(ms: number): string {
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function GlobalSearchProvider({ children }: { children: React.ReactNode }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const navigate = useNavigate();

  const run = useCallback(async (query: string) => {
    if (!query.trim()) { setHits(null); setBusy(false); setErr(""); return; }
    setBusy(true); setErr("");
    try {
      const res = await api(`/search?q=${encodeURIComponent(query.trim())}`);
      const body = await res.json();
      setHits(body.results);
    } catch (e: any) {
      setErr(e.message);
      setHits([]);
    } finally {
      setBusy(false);
    }
  }, []);

  // debounce; empty input clears immediately
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!q.trim()) { setHits(null); setErr(""); setBusy(false); return; }
    timer.current = window.setTimeout(() => run(q), 250);
    return () => window.clearTimeout(timer.current);
  }, [q, run]);

  const jump = (h: Hit) => {
    setQ(""); setHits(null);
    navigate(`/videos/${h.video_id}?t=${h.start_ms}`);
  };

  const value: GSearchState = { q, setQ, hits, busy, err };

  const searching = q.trim() !== "";

  return (
    <Ctx.Provider value={value}>
      <div className="container">
        {searching && (
          <div>
            {busy && <p className="muted">searching…</p>}
            {err && <p className="muted" style={{ color: "#f87171" }}>{err}</p>}
            {hits !== null && !busy && (
              <p className="muted">{hits.length} result{hits.length === 1 ? "" : "s"} for “{q}”</p>
            )}
            <div>
              {hits?.map((h, i) => (
                <div key={`${h.video_id}-${h.start_ms}-${i}`} className="card" style={{ cursor: "pointer" }} onClick={() => jump(h)}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {h.filename}
                    </div>
                    <div className="muted">
                      {fmt(h.start_ms)} · <span className="gheadline" dangerouslySetInnerHTML={{ __html: htmlEscape(h.headline) }} />
                    </div>
                  </div>
                  <span className="badge working">jump →</span>
                </div>
              ))}
              {hits !== null && hits.length === 0 && !busy && (
                <p className="muted" style={{ textAlign: "center" }}>nothing found</p>
              )}
            </div>
          </div>
        )}
        {!searching && children}
      </div>
    </Ctx.Provider>
  );
}

export function GlobalSearchInput() {
  const { q, setQ } = useGlobalSearch();
  return (
    <input
      className="gsearch-input"
      placeholder="🔍  search transcripts…"
      value={q}
      onChange={(e) => setQ(e.target.value)}
      onKeyDown={(e) => { if (e.key === "Escape") setQ(""); }}
      style={{ maxWidth: 340, width: "100%" }}
    />
  );
}
