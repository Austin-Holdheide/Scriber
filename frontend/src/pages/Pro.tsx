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
  ["Bulk upload", "Not included", "Included"],
  ["Queue priority", "Standard", "Priority"],
];

type Status = {
  enabled: boolean;
  plan: string;
  is_pro: boolean;
  has_customer: boolean;
  prices: { monthly: boolean; annual: boolean };
};

export default function Pro() {
  const [status, setStatus] = useState<Status | null>(null);
  const [onList, setOnList] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<"" | "month" | "year" | "portal" | "interest">("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/billing/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() =>
        setStatus({ enabled: false, plan: "free", is_pro: false, has_customer: false, prices: { monthly: false, annual: false } })
      );
  }, []);

  // the waiting list only matters while Pro cannot actually be bought
  useEffect(() => {
    if (!status || status.enabled) return;
    api("/me/interest").then((r) => r.json()).then((d) => setOnList(!!d.on_list)).catch(() => setOnList(false));
  }, [status]);

  const startCheckout = async (interval: "month" | "year") => {
    setBusy(interval); setErr("");
    try {
      const r = await api("/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interval }),
      });
      const d = await r.json();
      if (!d.url) throw new Error("no checkout url returned");
      // Stripe hosts the payment page: no card data ever reaches this app
      window.location.href = d.url;
    } catch (e: any) {
      setErr(e?.detail?.message || e?.message || "could not start checkout");
      setBusy("");
    }
  };

  const openPortal = async () => {
    setBusy("portal"); setErr("");
    try {
      const r = await api("/billing/portal", { method: "POST" });
      const d = await r.json();
      if (!d.url) throw new Error("no portal url returned");
      window.location.href = d.url;
    } catch (e: any) {
      setErr(e?.detail?.message || e?.message || "could not open billing");
      setBusy("");
    }
  };

  const joinList = async () => {
    setBusy("interest"); setErr("");
    try {
      const r = await api("/me/interest", { method: "POST" });
      const d = await r.json();
      setOnList(!!d.on_list);
    } catch (e: any) {
      setErr(e?.message || "could not save that");
    } finally {
      setBusy("");
    }
  };

  const canBuy = !!status?.enabled && !status.is_pro;

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
        {status?.is_pro ? (
          <>
            <p className="pro-price">You&apos;re on Pro.</p>
            <div className="pro-buttons">
              <button className="pro-button" onClick={openPortal} disabled={busy !== ""}>
                {busy === "portal" ? "…" : "Manage billing"}
              </button>
              <Link to="/" className="pro-secondary">Back to your videos</Link>
            </div>
            <p className="pro-note">
              Update your card, download invoices or cancel in the billing portal. Cancelling keeps Pro
              until the end of the period you already paid for.
            </p>
          </>
        ) : canBuy ? (
          <>
            <p className="pro-price">$9 a month, or $90 a year — two months free.</p>
            <div className="pro-buttons">
              <button className="pro-button" onClick={() => startCheckout("month")} disabled={busy !== ""}>
                {busy === "month" ? "…" : "Go Pro — $9/month"}
              </button>
              <button className="pro-button pro-button-alt" onClick={() => startCheckout("year")} disabled={busy !== ""}>
                {busy === "year" ? "…" : "Go Pro — $90/year"}
              </button>
            </div>
            <p className="pro-note">
              Payment is handled by Stripe on its own page, so Scribly never sees your card. Cancel any time.
            </p>
          </>
        ) : (
          <>
            <p className="pro-price">Pricing is announced when Pro opens — no card, nothing charged today.</p>
            {onList ? (
              <p className="pro-onlist">
                You&apos;re on the list — we&apos;ll email the address on your account when Pro opens.
              </p>
            ) : (
              <button className="pro-button" onClick={joinList} disabled={busy !== "" || onList === null}>
                {busy === "interest" ? "…" : "Request early access"}
              </button>
            )}
          </>
        )}

        {err && <p className="pro-err">{err}</p>}

        <p className="pro-note">Files are never deleted automatically — on any plan, nothing is removed until you delete it.</p>
        <p className="pro-fine">
          Unlimited means fair use: capacity is shared, so automated abuse or reselling it
          gets throttled — see the <a href="https://scribly.cc/terms.html">terms</a>. File
          size and length limits still apply, and the app always says so before it refuses anything.
        </p>
      </section>
    </div>
  );
}
