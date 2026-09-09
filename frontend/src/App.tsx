import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import Auth from "./components/Auth";
import Videos from "./components/Videos";

export default function App() {
  const [session, setSession] = useState<boolean | null>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(!!data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(!!s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (session === null) return <div className="container muted">loading…</div>;
  return (
    <div className="container">
      <header>
        <h1>✦ Scriber</h1>
        {session && (
          <button className="ghost" onClick={() => supabase.auth.signOut()}>
            sign out
          </button>
        )}
      </header>
      {session ? <Videos /> : <Auth />}
    </div>
  );
}
