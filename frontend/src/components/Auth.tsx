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

  return (
    <form onSubmit={submit} style={{ maxWidth: 360, margin: "4rem auto" }}>
      <h2 style={{ marginTop: 0 }}>{mode === "login" ? "Sign in" : "Create account"}</h2>
      <input
        type="email" placeholder="email" value={email} required
        onChange={(e) => setEmail(e.target.value)}
        style={{ marginBottom: "0.75rem" }}
      />
      <input
        type="password" placeholder="password" minLength={6} value={password} required
        onChange={(e) => setPassword(e.target.value)}
        style={{ marginBottom: "0.75rem" }}
      />
      {err && <p className="muted" style={{ color: "#f87171" }}>{err}</p>}
      <button disabled={busy} style={{ width: "100%" }}>
        {busy ? "…" : mode === "login" ? "Sign in" : "Sign up"}
      </button>
      <p className="muted" style={{ textAlign: "center" }}>
        <a href="#" onClick={(e) => { e.preventDefault(); setMode(mode === "login" ? "signup" : "login"); setErr(""); }}>
          {mode === "login" ? "no account? sign up" : "have an account? sign in"}
        </a>
      </p>
    </form>
  );
}
