import { useEffect, useState } from "react";
import { api } from "../lib/supabase";
import { copyText } from "../lib/clipboard";

type ShareRow = { id: string; token: string; expires_at: string; created_at: string; revoked: boolean; expired?: boolean };

export default function ShareModal({ videoId, filename, onClose }: { videoId: string; filename: string; onClose: () => void }) {
  const [links, setLinks] = useState<ShareRow[]>([]);
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");
  const [err, setErr] = useState("");

  const load = () => {
    api(`/videos/${videoId}/shares`).then((r) => r.json()).then(setLinks).catch((e) => setErr(e.message));
  };
  useEffect(load, [videoId]);

  const create = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api(`/videos/${videoId}/shares`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days }),
      });
      const row = await r.json();
      copy(`${location.origin}${row.url}`, row.token);
      load();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const revoke = async (id: string) => {
    try { await api(`/videos/shares/${id}`, { method: "DELETE" }); load(); }
    catch (e: any) { setErr(e.message); }
  };

  const copy = async (url: string, token: string) => {
    const ok = await copyText(url);
    if (ok) {
      setCopied(token);
      setTimeout(() => setCopied(""), 2500);
    } else {
      setCopied("failed:" + token);
      setTimeout(() => setCopied(""), 4000);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
        <h3>Share transcript</h3>
        <p className="muted" style={{ fontWeight: 600, margin: "0.25rem 0 0.75rem" }}>{filename}</p>
        <p className="muted">Anyone with the link can read this transcript until it expires. They cannot see the video, edit, or access anything else.</p>

        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", margin: "0.75rem 0" }}>
          <label className="muted">expires in</label>
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value))} style={{ width: 90 }}
            className="share-select">
            {[1, 3, 7, 14, 30].map((d) => <option key={d} value={d}>{d} day{d > 1 ? "s" : ""}</option>)}
          </select>
          <button disabled={busy} onClick={create}>{busy ? "creating…" : "+ create link"}</button>
        </div>
        {err && <p className="muted" style={{ color: "#f87171" }}>{err}</p>}

        <div style={{ maxHeight: 260, overflowY: "auto" }}>
          {links.map((s) => {
            const dead = s.revoked || s.expired;
            const url = `${location.origin}/share/${s.token}`;
            return (
              <div key={s.id} className="share-row">
                <code style={{ flex: 1, fontSize: "0.75rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textDecoration: dead ? "line-through" : "none", opacity: dead ? 0.5 : 1 }}>
                  {url}
                </code>
                {!dead && (
                  <>
                    <button className="ghost sm" onClick={() => copy(url, s.token)}>
                      {copied === s.token ? "✓ copied" : copied === "failed:" + s.token ? "select + Ctrl+C" : "copy"}
                    </button>
                    <button className="ghost sm stop" onClick={() => revoke(s.id)}>revoke</button>
                  </>
                )}
                {dead && <span className="muted">{s.revoked ? "revoked" : "expired"}</span>}
                {!dead && <span className="muted">expires {new Date(s.expires_at).toLocaleDateString()}</span>}
              </div>
            );
          })}
          {links.length === 0 && <p className="muted" style={{ textAlign: "center" }}>no links yet</p>}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "0.75rem" }}>
          <button className="ghost" onClick={onClose}>close</button>
        </div>
      </div>
    </div>
  );
}
