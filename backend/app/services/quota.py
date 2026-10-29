"""F-7 / T-3: plan entitlements and per-user usage accounting.

One place decides what an account may do. Callers ask for a Plan, or call a
check_* function which raises a structured HTTPException the frontend can turn
into a sentence.

Limits are env-overridable so a dev box can use tiny values (QUOTA_FREE_*)
without shipping different code.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.services.supabase_client import admin_client

log = logging.getLogger("scriber.quota")

MB = 1024 * 1024
# Entitlement convention: -1 = unlimited, 0 = not available on this plan, n = cap.
# (0 used to mean "unlimited", which silently gave free accounts diarization because
#  "0 per day" and "no limit" were the same number. Keep the two ideas apart.)
UNLIMITED = -1


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("ignoring non-integer %s=%r", name, raw)
        return default


@dataclass(frozen=True)
class Plan:
    name: str
    max_upload_bytes: int      # 0 = unlimited
    max_duration_s: int        # 0 = unlimited
    uploads_per_window: int    # 0 = unlimited
    window_s: int              # rolling window for uploads_per_window
    diarizations_per_day: int  # 0 = not available on this plan
    share_max_days: int
    retention_days: int        # 0 = kept indefinitely
    queue: str                 # RQ priority lane (F-8 wires this up)


PLANS: dict[str, Plan] = {
    "free": Plan(
        name="free",
        max_upload_bytes=_env_int("QUOTA_FREE_MAX_UPLOAD_MB", 500) * MB,
        max_duration_s=_env_int("QUOTA_FREE_MAX_DURATION_S", 15 * 60),
        uploads_per_window=_env_int("QUOTA_FREE_UPLOADS", 1),
        window_s=_env_int("QUOTA_FREE_WINDOW_S", 24 * 3600),
        diarizations_per_day=_env_int("QUOTA_FREE_DIARIZATIONS", 0),
        share_max_days=7,
        retention_days=7,
        queue="low",
    ),
    "premium": Plan(
        name="premium",
        max_upload_bytes=_env_int("QUOTA_PREMIUM_MAX_UPLOAD_MB", 5 * 1024) * MB,
        max_duration_s=_env_int("QUOTA_PREMIUM_MAX_DURATION_S", 24 * 3600),
        uploads_per_window=_env_int("QUOTA_PREMIUM_UPLOADS", 50),
        window_s=_env_int("QUOTA_PREMIUM_WINDOW_S", 12 * 3600),
        diarizations_per_day=_env_int("QUOTA_PREMIUM_DIARIZATIONS", 10),
        share_max_days=30,
        retention_days=0,
        queue="high",
    ),
    # operator account: everything unlimited
    "admin": Plan(
        name="admin",
        max_upload_bytes=UNLIMITED,
        max_duration_s=UNLIMITED,
        uploads_per_window=UNLIMITED,
        window_s=0,
        diarizations_per_day=UNLIMITED,
        share_max_days=30,
        retention_days=0,
        queue="high",
    ),
}

DEFAULT_PLAN = "free"


# ---------------------------------------------------------------- plan lookup

def plan_name_for(user_id: str) -> str:
    """The account's plan, tolerating a missing row or an unreachable database."""
    try:
        r = (admin_client().table("subscriptions")
             .select("plan,status").eq("user_id", user_id).limit(1).execute())
    except Exception:
        log.exception("subscription lookup failed for %s; falling back to free", user_id)
        return DEFAULT_PLAN
    if not r.data:
        return DEFAULT_PLAN
    row = r.data[0]
    # a canceled or unpaid subscription does not keep premium entitlements
    if row.get("status") in ("canceled", "past_due"):
        return DEFAULT_PLAN
    return row.get("plan") or DEFAULT_PLAN


def plan_for(user_id: str) -> Plan:
    return PLANS.get(plan_name_for(user_id), PLANS[DEFAULT_PLAN])


def set_plan(user_id: str, plan: str, status: str = "active", **fields) -> dict:
    if plan not in PLANS:
        raise ValueError(f"unknown plan {plan!r}")
    payload = {"user_id": user_id, "plan": plan, "status": status, **fields}
    r = (admin_client().table("subscriptions")
         .upsert(payload, on_conflict="user_id").execute())
    return (r.data or [{}])[0]


# ------------------------------------------------------------------- metering

def _window_start(window_s: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=window_s)


def used(user_id: str, kind: str, window_s: int) -> int:
    since = _window_start(window_s).isoformat()
    try:
        r = (admin_client().table("usage_events")
             .select("id", count="exact")
             .eq("user_id", user_id).eq("kind", kind)
             .gte("created_at", since).execute())
        return r.count or 0
    except Exception:
        log.exception("usage count failed for %s/%s; assuming 0", user_id, kind)
        return 0


def record(user_id: str, kind: str, video_id: str | None = None, quantity: int = 1) -> None:
    """Log usage AFTER the work is accepted. Never let this break a request."""
    rows = [{"user_id": user_id, "kind": kind, "video_id": video_id} for _ in range(max(1, quantity))]
    try:
        admin_client().table("usage_events").insert(rows).execute()
    except Exception:
        log.exception("usage record failed for %s/%s", user_id, kind)


# -------------------------------------------------------------------- errors

def _resets_at(user_id: str, kind: str, window_s: int) -> str | None:
    """When the oldest counted event ages out of the window, one slot frees up."""
    if not window_s:
        return None
    since = _window_start(window_s).isoformat()
    try:
        r = (admin_client().table("usage_events")
             .select("created_at")
             .eq("user_id", user_id).eq("kind", kind)
             .gte("created_at", since)
             .order("created_at").limit(1).execute())
        if r.data:
            oldest = datetime.fromisoformat(r.data[0]["created_at"].replace("Z", "+00:00"))
            return (oldest + timedelta(seconds=window_s)).isoformat()
    except Exception:
        log.exception("reset-time lookup failed for %s/%s", user_id, kind)
    return None


def _quota_exceeded(user_id: str, plan: Plan, kind: str, limit: int, seen: int) -> HTTPException:
    resets = _resets_at(user_id, kind, plan.window_s)
    return HTTPException(429, detail={
        "error": "quota_exceeded",
        "kind": kind,
        "plan": plan.name,
        "limit": limit,
        "used": seen,
        "window_s": plan.window_s,
        "resets_at": resets,
        "message": f"You've used all {limit} of your {kind} allowance on the {plan.name} plan.",
    })


def _feature_locked(plan: Plan, feature: str) -> HTTPException:
    return HTTPException(402, detail={
        "error": "feature_locked",
        "feature": feature,
        "plan": plan.name,
        "message": f"{feature.capitalize()} isn't included on the {plan.name} plan.",
    })


def _too_big(plan: Plan, limit: int, seen: int) -> HTTPException:
    return HTTPException(413, detail={
        "error": "upload_too_large",
        "plan": plan.name,
        "limit_bytes": limit,
        "size_bytes": seen,
        "message": f"That file is larger than the {round(limit / MB)} MB allowed on the {plan.name} plan.",
    })


def fmt_duration(seconds: float) -> str:
    """'90 s' / '15 min' / '1.5 min' — never '0 min'."""
    if seconds < 60:
        return f"{round(seconds)} s"
    if seconds % 60 == 0:
        return f"{round(seconds // 60)} min"
    return f"{seconds / 60:.1f} min"


def _too_long(plan: Plan, limit_s: int, seen_s: float) -> HTTPException:
    return HTTPException(422, detail={
        "error": "media_too_long",
        "plan": plan.name,
        "limit_s": limit_s,
        "duration_s": round(seen_s, 1),
        "message": (
            f"That file is {fmt_duration(seen_s)} long; the {plan.name} plan allows "
            f"{fmt_duration(limit_s)} per file."
        ),
    })


# -------------------------------------------------------------------- checks

def check_transcription(user_id: str) -> Plan:
    """Raise before a byte is written if this upload is not allowed."""
    plan = plan_for(user_id)
    if plan.uploads_per_window < 0:
        return plan
    seen = used(user_id, "transcription", plan.window_s)
    if seen >= plan.uploads_per_window:
        raise _quota_exceeded(user_id, plan, "transcription", plan.uploads_per_window, seen)
    return plan


def check_size(plan: Plan, size_bytes: int) -> None:
    if plan.max_upload_bytes >= 0 and size_bytes > plan.max_upload_bytes:
        raise _too_big(plan, plan.max_upload_bytes, size_bytes)


def check_duration(plan: Plan, duration_s: float | None) -> None:
    if duration_s is None or plan.max_duration_s < 0:
        return
    if duration_s > plan.max_duration_s:
        raise _too_long(plan, plan.max_duration_s, duration_s)


def check_diarization(user_id: str) -> Plan:
    plan = plan_for(user_id)
    if plan.diarizations_per_day < 0:      # unlimited (operator)
        return plan
    if plan.diarizations_per_day == 0:     # not offered on this plan
        raise _feature_locked(plan, "speaker diarization")
    seen = used(user_id, "diarization", 24 * 3600)
    if seen >= plan.diarizations_per_day:
        raise _quota_exceeded(user_id, plan, "diarization", plan.diarizations_per_day, seen)
    return plan


def share_days_for(user_id: str, requested: int | None) -> int:
    """Clamp a requested share-link lifetime to the plan's maximum."""
    plan = plan_for(user_id)
    days = 7 if requested is None else max(1, int(requested))
    return max(1, min(days, plan.share_max_days))


# ------------------------------------------------------------------ reporting

def limits_payload(user_id: str) -> dict:
    """Everything the UI needs to explain the account's allowance."""
    plan = plan_for(user_id)
    transcriptions_used = (
        0 if plan.uploads_per_window < 0
        else used(user_id, "transcription", plan.window_s)
    )
    diarizations_used = 0 if plan.diarizations_per_day < 0 else used(
        user_id, "diarization", 24 * 3600
    )
    return {
        "plan": plan.name,
        "limits": {
            "max_upload_bytes": plan.max_upload_bytes,
            "max_duration_s": plan.max_duration_s,
            "uploads_per_window": plan.uploads_per_window,
            "window_s": plan.window_s,
            "diarizations_per_day": plan.diarizations_per_day,
            "share_max_days": plan.share_max_days,
            "retention_days": plan.retention_days,
        },
        "usage": {
            "transcriptions_in_window": transcriptions_used,
            "transcriptions_left": (
                None if plan.uploads_per_window < 0
                else max(0, plan.uploads_per_window - transcriptions_used)
            ),
            "diarizations_today": diarizations_used,
            "diarizations_left": (
                None if plan.diarizations_per_day < 0
                else max(0, plan.diarizations_per_day - diarizations_used)
            ),
        },
    }
