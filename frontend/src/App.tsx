import { useEffect, useState } from "react";
import { Link, Route, Routes as RR_Routes } from "react-router-dom";
import { GlobalSearchInput, SearchResultsBody, useGlobalSearch } from "./components/GlobalSearch";
import { supabase } from "./lib/supabase";
import Auth from "./components/Auth";
import Videos from "./components/Videos";
import SearchPage from "./pages/SearchPage";
import VideoPage from "./pages/VideoPage";

export default function App() {
  const [session, setSession] = useState<boolean | null>(null);
  const { q } = useGlobalSearch();
  const searching = q.trim() !== "";

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(!!data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(!!s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (session === null) return <div className="container muted">loading…</div>;

  return (
    <div className="container">
      <header>
          <h1><Link to="/" style={{ color: "inherit", textDecoration: "none" }}>✦ Scriber</Link></h1>
          {session && <GlobalSearchInput />}
          {session && <button className="ghost" onClick={() => supabase.auth.signOut()}>sign out</button>}
        </header>
      {searching && session ? (
        <SearchResultsBody />
      ) : (
        <RR_Routes>
          <Route path="/" element={session ? <Videos /> : <Auth />} />
          <Route path="/videos/:videoId" element={session ? <VideoPage /> : <Auth />} />
          <Route path="/search" element={session ? <SearchPage /> : <Auth />} />
        </RR_Routes>
      )}
    </div>
  );
}
