import { useState } from "react";
import { supabase } from "../lib/supabase";

export default function Auth() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    const fn = mode === "login"
      ? supabase.auth.signInWithPassword({ email, password })
      : supabase.auth.signUp({ email, password });
    const { error } = await fn;
    setBusy(false);
    if (error) setErr(error.message);
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
        <p className="auth-tagline">Video in. Searchable transcript out.</p>

        <form className="auth-card" onSubmit={submit}>
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

          <p className="auth-switch">
            {mode === "login" ? "No account yet?" : "Already have an account?"}{" "}
            <a
              href="#"
              onClick={(e) => { e.preventDefault(); switchMode(mode === "login" ? "signup" : "login"); }}
            >
              {mode === "login" ? "Create one" : "Sign in"}
            </a>
          </p>
        </form>

        <p className="auth-legal">
          By continuing you agree to the <a href="https://scribly.cc/terms.html">terms</a> and{" "}
          <a href="https://scribly.cc/privacy.html">privacy</a> policy.
        </p>
      </div>
    </div>
  );
}
