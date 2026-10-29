"""Account-level endpoints: what this user's plan allows, and (for the operator)
setting a plan by hand until Stripe exists."""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import get_current_user
from app.services import quota

log = logging.getLogger("scriber.me")
router = APIRouter()


@router.get("/limits")
def my_limits(user_id: str = Depends(get_current_user)):
    """Plan, entitlements and current usage — everything the UI needs to be honest."""
    return quota.limits_payload(user_id)


@router.post("/plan")
def change_plan(body: dict, user_id: str = Depends(get_current_user)):
    """Operator-only: move an account between plans (stand-in until Stripe webhooks).

    body: {"user_id": "<uuid>", "plan": "premium"|"free"|"admin", "status"?: "active"}
    """
    if quota.plan_for(user_id).name != "admin":
        raise HTTPException(403, "only an admin account can change plans")

    target = (body or {}).get("user_id")
    plan = (body or {}).get("plan")
    if not target:
        raise HTTPException(422, "user_id is required")
    if plan not in quota.PLANS:
        raise HTTPException(422, f"plan must be one of {sorted(quota.PLANS)}")

    try:
        row = quota.set_plan(target, plan, status=(body.get("status") or "active"))
    except Exception as exc:
        log.exception("plan change failed")
        raise HTTPException(500, f"plan change failed: {exc}")

    log.info("plan changed: %s -> %s by %s", target, plan, user_id)
    return {"user_id": target, "plan": row.get("plan", plan), "status": row.get("status", "active")}
