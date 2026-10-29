import { createClient } from "@supabase/supabase-js";

// Anon key is PUBLIC by design — RLS enforces what anon can do.
// Values injected at build time via Vite env vars.
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL as string,
  import.meta.env.VITE_SUPABASE_ANON_KEY as string,
);

const callApi = (path: string, init: RequestInit, token?: string) =>
  fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

export const api = async (path: string, init: RequestInit = {}) => {
  // A fresh document boot (or a long-idle tab) can reach the app before supabase-js has
  // restored the stored session. Sending no Authorization header makes list calls come
  // back empty/401, which reads to the user as "my videos disappeared until I refresh".
  let { data } = await supabase.auth.getSession();
  let token = data.session?.access_token;

  if (!token) {
    const refreshed = await supabase.auth.refreshSession().catch(() => null);
    token = (refreshed as any)?.data?.session?.access_token;
  }

  let res = await callApi(path, init, token);

  // Expired token: refresh once and replay the request.
  if ((res.status === 401 || res.status === 403) && token) {
    const refreshed = await supabase.auth.refreshSession().catch(() => null);
    const fresh = (refreshed as any)?.data?.session?.access_token;
    if (fresh && fresh !== token) res = await callApi(path, init, fresh);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const d = body.detail;
    const msg = typeof d === "string" ? d
      : Array.isArray(d) ? d.map((x: any) => x.msg || x.message).join("; ")
      : (d?.message || d?.msg || JSON.stringify(body));
    // Keep the structured detail: callers distinguish plan limits (detail.error)
    // from ordinary failures and show a proper notification for the former.
    const err = new Error(msg || `${res.status} ${res.statusText}`) as Error & {
      detail?: unknown; status?: number;
    };
    if (d && typeof d === "object") err.detail = d;
    err.status = res.status;
    throw err;
  }
  return res;
};
