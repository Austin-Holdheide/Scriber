import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/supabase";

/**
 * Where Stripe sends the browser after a successful payment.
 *
 * The webhook is what actually grants Pro, and it may land a moment after the
 * redirect, so this polls /me/limits for a few seconds instead of trusting the
 * URL. If it never arrives we say so plainly rather than showing a fake success.
 */
export default function BillingSuccess() {
  const [params] = useSearchParams();
  const sessionId = params.get("session_id");
  const [state, setState] = useState<"checking" | "pro" | "waiting">("checking");

  useEffect(() => {
    let tries = 0;
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      tries += 1;
      try {
        const r = await api("/me/limits");
        const d = await r.json();
        if (alive && d?.plan === "premium") { setState("pro"); return; }
      } catch { /* keep waiting */ }
      if (!alive) return;
      if (tries >= 8) { setState("waiting"); return; }
      setTimeout(tick, 1500);
    };
    tick();
    return () => { alive = false; };
  }, []);

  return (
    <div className="container pro-page">
      <div className="pro-hero">
        <div className="pro-wordmark">
          <svg className="pro-spark" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 2.5c.5 4.6 2.4 6.9 9 9.5-6.6 2.6-8.5 4.9-9 9.5-.5-4.6-2.4-6.9-9-9.5 6.6-2.6 8.5-4.9 9-9.5Z" fill="currentColor" />
          </svg>
          Scribly <span className="pro-badge">Pro</span>
        </div>

        {state === "checking" && (
          <>
            <h1 className="pro-title">Confirming your payment…</h1>
            <p className="pro-sub">This takes a few seconds. Don&apos;t close the tab.</p>
          </>
        )}

        {state === "pro" && (
          <>
            <h1 className="pro-title">You&apos;re on Pro.</h1>
            <p className="pro-sub">
              Unlimited transcriptions (fair use), 5 GB uploads, 24-hour files, speaker labels and
              30-day share links are all live on your account now.
            </p>
            <div className="pro-buttons">
              <Link to="/" className="pro-button">Upload something</Link>
              <Link to="/pro" className="pro-secondary">Manage billing</Link>
            </div>
          </>
        )}

        {state === "waiting" && (
          <>
            <h1 className="pro-title">Payment received.</h1>
            <p className="pro-sub">
              Stripe took the payment, but the upgrade hasn&apos;t reached your account yet — it can take
              a minute. Reload this page, and if Pro is still missing after that, email us with the
              reference below and we&apos;ll sort it.
            </p>
            {sessionId && (
              <p className="pro-note">
                Reference: <code>{sessionId}</code>
              </p>
            )}
            <div className="pro-buttons">
              <Link to="/" className="pro-button">Back to your videos</Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
