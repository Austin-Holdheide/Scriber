import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/supabase";

/** What Pro changes, per plan: [free, pro] */
const ROWS: Array<[string, string, string]> = [
  ["File size", "500 MB", "5 GB"],
  ["Length per file", "15 min", "24 hours"],
  ["Transcriptions", "1 per day", "Unlimited"],
  ["Speaker diarization", "Not included", "10 per day"],
  ["Share links live for", "7 days", "30 days"],
  ["Your files are kept for", "7 days", "Until you delete them"],
  ["Bulk upload", "Not included", "Included"],
  ["Queue priority", "Standard", "Priority"],
];

export default function Pro() {
  const [onList, setOnList] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/me/interest")
      .then((r) => r.json())
      .then((d) => setOnList(!!d.on_list))
      .catch(() => setOnList(false));
  }, []);

  const request = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api("/me/interest", { method: "POST" });
      const d = await r.json();
      setOnList(!!d.on_list);
    } catch (e: any) {
      setErr(e.message || "could not save that");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="container pro-page">
      <Link to="/" className="pro-back">← back to your videos</Link>

      <div className="pro-hero">
        <div className="pro-wordmark">
          <svg className="pro-spark" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 2.5c.5 4.6 2.4 6.9 9 9.5-6.6 2.6-8.5 4.9-9 9.5-.5-4.6-2.4-6.9-9-9.5 6.6-2.6 8.5-4.9 9-9.5Z" fill="currentColor" />
          </svg>
          Scribly <span className="pro-badge">Pro</span>
        </div>
        <h1 className="pro-title">For the videos that take all afternoon.</h1>
        <p className="pro-sub">
          Free gets you one transcription a day of up to 15 minutes. Pro lifts the ceiling:
          whole-day recordings, five gigabyte uploads, speaker labels, and files that stay
          until you decide otherwise.
        </p>
      </div>

      <table className="pro-table">
        <thead>
          <tr>
            <th scope="col"></th>
            <th scope="col">Free</th>
            <th scope="col" className="pro-col">Pro</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([label, free, pro]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{free}</td>
              <td className="pro-col">{pro}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <section className="pro-cta">
        <p className="pro-price">Pricing is announced when Pro opens — no card, nothing charged today.</p>

        {onList ? (
          <p className="pro-onlist">
            You&apos;re on the list — we&apos;ll email the address on your account when Pro opens.
          </p>
        ) : (
          <button className="pro-button" onClick={request} disabled={busy || onList === null}>
            {busy ? "…" : "Request early access"}
          </button>
        )}
        {err && <p className="pro-err">{err}</p>}

        <p className="pro-fine">
          Unlimited means fair use: capacity is shared, so automated abuse or reselling it
          gets throttled — see the <a href="https://scribly.cc/terms.html">terms</a>. File
          size and length limits still apply, and the app always says so before it refuses anything.
        </p>
      </section>
    </div>
  );
}
