import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

// Signup can be closed at the identity provider (GOTRUE_DISABLE_SIGNUP). When it is,
// offering "create account" only produces a cryptic 422, so the tabs are hidden.
const SIGNUP_ENABLED = import.meta.env.VITE_SIGNUP_ENABLED !== "false";

type Props = {
  /** arrived from a password-reset email: show "choose a new password" instead of sign in */
  recovery?: boolean;
  onRecoveryDone?: () => void;
};

export default function Auth({ recovery = false, onRecoveryDone }: Props) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  // recovery mode state
  const [npw, setNpw] = useState("");
  const [npw2, setNpw2] = useState("");
  const [done, setDone] = useState(false);

  // signup with email verification: no session yet, so tell them what to do next
  const [sentTo, setSentTo] = useState("");
  const [resent, setResent] = useState(false);

  useEffect(() => {
    if (!recovery) return;
    // the one-time tokens are in the hash; drop them from the address bar once consumed
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
  }, [recovery]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    const fn = mode === "login"
      ? supabase.auth.signInWithPassword({ email, password })
      : supabase.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: `${window.location.origin}/` },
        });
    const { data, error } = await fn;
    setBusy(false);
    if (error) {
      // unconfirmed accounts cannot sign in until they click the link
      if (/email not confirmed/i.test(error.message)) {
        setSentTo(email.trim());
        setErr("");
        return;
      }
      // GoTrue throttles repeated auth emails per address (RATE_LIMIT / SMTP_MAX_FREQUENCY)
      if (/can only request this after/i.test(error.message)) {
        return setErr("We just sent an email to that address — give it a minute, then try again.");
      }
      return setErr(error.message);
    }
    if (mode === "signup" && !data.session) {
      setSentTo(email.trim());
      setResent(false);
      return;
    }
  };

  const resend = async () => {
    setBusy(true);
    const { error } = await supabase.auth.resend({
      type: "signup",
      email: sentTo,
      options: { emailRedirectTo: `${window.location.origin}/` },
    });
    setBusy(false);
    if (error) return setErr(error.message);
    setResent(true);
  };

  const submitRecovery = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    if (npw.length < 6) return setErr("Password must be at least 6 characters.");
    if (npw !== npw2) return setErr("The two passwords do not match.");
    setBusy(true);
    const { error } = await supabase.auth.updateUser({ password: npw });
    setBusy(false);
    if (error) return setErr(error.message);
    setDone(true);
    setTimeout(() => onRecoveryDone?.(), 900);
  };

  const forgot = async () => {
    setErr("");
    const addr = email.trim();
    if (!addr) return setErr("Enter your email above first, then click “Forgot password?”.");
    setBusy(true);
    const { error } = await supabase.auth.resetPasswordForEmail(addr, {
      redirectTo: `${window.location.origin}/`,
    });
    setBusy(false);
    setErr(error ? error.message : "If that address has an account, a reset link is on its way.");
  };

  const switchMode = (m: "login" | "signup") => { setMode(m); setErr(""); };

  return (
    <div className="auth-wrap">
      <div className="auth-glow" aria-hidden="true" />

      <div className="auth-panel">
        <a className="auth-brand" href="https://scribly.cc">
          <svg className="auth-spark" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M12 2.5c.5 4.6 2.4 6.9 9 9.5-6.6 2.6-8.5 4.9-9 9.5-.5-4.6-2.4-6.9-9-9.5 6.6-2.6 8.5-4.9 9-9.5Z"
              fill="currentColor"
            />
          </svg>
          Scribly
        </a>
        <p className="auth-tagline">
          {recovery ? "Choose a new password for your account" : "Video in. Searchable transcript out."}
        </p>

        {recovery ? (
          <form className="auth-card" onSubmit={submitRecovery}>
            {done ? (
              <p className="auth-success">Password updated. Taking you in…</p>
            ) : (
              <>
                <label className="auth-label" htmlFor="auth-newpw">New password</label>
                <input
                  id="auth-newpw"
                  type="password"
                  placeholder="at least 6 characters"
                  minLength={6}
                  value={npw}
                  required
                  autoComplete="new-password"
                  onChange={(e) => setNpw(e.target.value)}
                />

                <label className="auth-label" htmlFor="auth-newpw2">Confirm new password</label>
                <input
                  id="auth-newpw2"
                  type="password"
                  placeholder="type it again"
                  minLength={6}
                  value={npw2}
                  required
                  autoComplete="new-password"
                  onChange={(e) => setNpw2(e.target.value)}
                />

                {err && <p className="auth-error">{err}</p>}

                <button className="auth-submit" disabled={busy}>
                  {busy ? "…" : "Set new password"}
                </button>
              </>
            )}
          </form>
        ) : sentTo ? (
          <div className="auth-card">
            <h2 style={{ margin: "0 0 10px", fontSize: "1.05rem", color: "#e8ebef" }}>
              Confirm your email
            </h2>
            <p className="auth-note">
              We sent a link to <strong style={{ color: "#e8ebef" }}>{sentTo}</strong>. Click it
              to activate your account, then sign in.
            </p>
            <p className="auth-note" style={{ marginTop: "-4px" }}>
              Nothing after a minute? Check spam, or resend.
            </p>
            {resent && <p className="auth-success">Sent again — give it a minute.</p>}
            {err && <p className="auth-error">{err}</p>}
            <button className="auth-submit" onClick={resend} disabled={busy}>
              {busy ? "…" : "Resend email"}
            </button>
            <p className="auth-switch">
              <a href="#" onClick={(e) => { e.preventDefault(); setSentTo(""); setErr(""); }}>
                Use a different email
              </a>
            </p>
          </div>
        ) : (
          <form className="auth-card" onSubmit={submit}>
            {SIGNUP_ENABLED && (
            <div className="auth-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "login"}
                className={mode === "login" ? "auth-tab active" : "auth-tab"}
                onClick={() => switchMode("login")}
              >
                Sign in
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "signup"}
                className={mode === "signup" ? "auth-tab active" : "auth-tab"}
                onClick={() => switchMode("signup")}
              >
                Create account
              </button>
            </div>
            )}

            <label className="auth-label" htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              placeholder="you@example.com"
              value={email}
              required
              autoComplete="email"
              onChange={(e) => setEmail(e.target.value)}
            />

            <label className="auth-label" htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              placeholder={mode === "signup" ? "at least 6 characters" : "your password"}
              minLength={6}
              value={password}
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              onChange={(e) => setPassword(e.target.value)}
            />

            {err && <p className="auth-error">{err}</p>}

            <button className="auth-submit" disabled={busy}>
              {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
            </button>

            {SIGNUP_ENABLED && (
            <p className="auth-switch">
              {mode === "login" ? "No account yet?" : "Already have an account?"}{" "}
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); switchMode(mode === "login" ? "signup" : "login"); }}
              >
                {mode === "login" ? "Create one" : "Sign in"}
              </a>
            </p>
            )}

            <p className="auth-switch">
              <a href="#" onClick={(e) => { e.preventDefault(); forgot(); }}>Forgot password?</a>
            </p>
          </form>
        )}

        <p className="auth-legal">
          By continuing you agree to the <a href="https://scribly.cc/terms.html">terms</a> and{" "}
          <a href="https://scribly.cc/privacy.html">privacy</a> policy.
        </p>
      </div>
    </div>
  );
}
