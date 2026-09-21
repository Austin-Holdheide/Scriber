import { useEffect, useState } from "react";
import { api } from "../lib/supabase";
import type { Segment } from "../lib/types";

type Entry = { old: string; value: string; count: number };

export default function SpeakerRename({ videoId, onClose }: { videoId: string; onClose: () => void }) {
  const [rows, setRows] = useState<Entry[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    api(`/videos/${videoId}/transcript`)
      .then((r) => r.json())
      .then((d: { segments: Segment[] }) => {
        const counts = new Map<string, number>();
        for (const s of d.segments) {
          const spk = s.speaker?.trim();
          if (spk) counts.set(spk, (counts.get(spk) ?? 0) + 1);
        }
        setRows(
          [...counts.entries()]
            .sort((a, b) => b[1] - a[1])
            .map(([spk, n]) => ({ old: spk, value: "", count: n })),
        );
      })
      .catch((e) => setErr(e.message));
  }, [videoId]);

  const save = async () => {
    const mapping: Record<string, string> = {};
    for (const r of rows) {
      if (r.value.trim() && r.value.trim() !== r.old) mapping[r.old] = r.value.trim();
    }
    if (!Object.keys(mapping).length) { onClose(); return; }
    setBusy(true); setErr("");
    try {
      await api(`/videos/${videoId}/speakers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mapping }),
      });
      setDone(true);
      setTimeout(onClose, 900);
    } catch (e: any) {
      setErr(e.message);
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => !busy && onClose()}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        {done ? (
          <>
            <h3>Speakers renamed ✓</h3>
            <p className="muted">The transcript now shows the new names.</p>
          </>
        ) : (
          <>
            <h3>Rename speakers</h3>
            <p className="muted">Give each detected voice a real name. Leave blank to keep as-is.</p>
            {err && <p className="muted" style={{ color: "#f87171" }}>{err}</p>}
            <div style={{ margin: "0.75rem 0", maxHeight: 300, overflowY: "auto" }}>
              {rows.map((r, i) => (
                <div key={r.old} className="rename-row">
                  <code>{r.old}</code>
                  <span className="muted">×{r.count}</span>
                  <span className="muted">→</span>
                  <input
                    placeholder="real name…"
                    value={r.value}
                    onChange={(e) => {
                      const next = [...rows];
                      next[i] = { ...r, value: e.target.value };
                      setRows(next);
                    }}
                  />
                </div>
              ))}
              {rows.length === 0 && (
                <p className="muted">No speakers detected yet. Run "Detect speakers" first.</p>
              )}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "1rem" }}>
              <button className="ghost" disabled={busy} onClick={onClose}>cancel</button>
              <button disabled={busy || rows.length === 0} onClick={save}>
                {busy ? "renaming…" : "rename"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
