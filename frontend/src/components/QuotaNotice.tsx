import { useEffect } from "react";

/**
 * Plan-limit notice.
 *
 * When the API refuses work because of the account's plan (quota_exceeded,
 * feature_locked, upload_too_large, media_too_long) the user gets a proper
 * notification instead of a red line of text: what happened, what the plan
 * allows, and when it resets. It dismisses itself, but can be closed at once.
 */
export type QuotaDetail = {
  error?: string;
  message?: string;
  plan?: string;
  kind?: string;
  limit?: number;
  used?: number;
  limit_bytes?: number;
  size_bytes?: number;
  limit_s?: number;
  duration_s?: number;
  resets_at?: string | null;
  feature?: string;
};

const COPY: Record<string, { title: string; hint?: string }> = {
  quota_exceeded: { title: "You've reached your plan limit" },
  feature_locked: { title: "Not included in your plan" },
  upload_too_large: { title: "That file is too large" },
  media_too_long: { title: "That video is too long" },
};

const mb = (bytes?: number) => (bytes ? Math.round(bytes / 1048576) : 0);

function whenResets(iso?: string | null): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const mins = Math.max(0, Math.round((t - Date.now()) / 60000));
  if (mins < 1) return "resets in under a minute";
  if (mins < 60) return `resets in ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `resets in ${hrs} h`;
  const days = Math.round(hrs / 24);
  return `resets in ${days} day${days === 1 ? "" : "s"}`;
}

function hintFor(d: QuotaDetail): string | null {
  if (d.error === "quota_exceeded") {
    // the message already names the plan; the hint adds only the timing
    return whenResets(d.resets_at);
  }
  if (d.error === "feature_locked") {
    return "available on the premium plan";
  }
  if (d.error === "upload_too_large") {
    return `${mb(d.size_bytes)} MB sent · ${mb(d.limit_bytes)} MB allowed`;
  }
  if (d.error === "media_too_long") {
    const seen = d.duration_s ? Math.round(d.duration_s / 60) : null;
    const cap = d.limit_s ? Math.round(d.limit_s / 60) : null;
    return seen && cap ? `${seen} min long · ${cap} min allowed` : null;
  }
  return null;
}

export default function QuotaNotice({ detail, onClose }: { detail: QuotaDetail | null; onClose: () => void }) {
  const open = !!detail;
  const meta = (detail && COPY[detail.error || ""]) || { title: "Plan limit" };
  const hint = detail ? hintFor(detail) : null;

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(onClose, 15000);
    return () => clearTimeout(t);
  }, [open, detail, onClose]);

  if (!detail) return null;

  return (
    <div className="quota-pop" role="alert" aria-live="assertive">
      <div className="quota-pop-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20">
          <path d="M12 3.2 21 19.2H3z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
          <path d="M12 9.4v4.1M12 16.4v.1" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
        </svg>
      </div>
      <div className="quota-pop-body">
        <p className="quota-pop-title">{meta.title}</p>
        <p className="quota-pop-msg">{detail.message || "This action isn't allowed on your current plan."}</p>
        {hint && <p className="quota-pop-hint">{hint}</p>}
      </div>
      <button className="quota-pop-close" onClick={onClose} aria-label="Dismiss">
        ×
      </button>
    </div>
  );
}
