"""Billing endpoints (T-1): Checkout, Billing Portal, and the Stripe webhook.

The rule everywhere here: **Stripe is the source of truth for money, our DB is the
source of truth for entitlement.** The webhook translates a subscription into
`subscriptions` (plan, status, period end); `quota.py` reads that row and nothing
else, so a bug in billing can only ever write a plan row that the rest of the app
already knows how to enforce.

Idempotency matters because Stripe retries deliveries: every event id is recorded
in `stripe_events` before it is applied, and a repeat is a no-op.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.services import quota, stripe_api
from app.services.auth import get_current_user
from app.services.supabase_client import admin_client

log = logging.getLogger("scriber.billing")
router = APIRouter()

PRO_PLAN = "premium"


class CheckoutBody(BaseModel):
    interval: str = "month"   # "month" | "year"


def _price_for(interval: str) -> str:
    price = settings.stripe_price_annual if interval == "year" else settings.stripe_price_monthly
    if not price:
        raise HTTPException(503, "billing is not configured")
    return price


def _plan_for_price(price_id: str | None) -> str:
    """Which plan a Stripe price buys. Anything unrecognised stays free."""
    if price_id and price_id in (settings.stripe_price_monthly, settings.stripe_price_annual):
        return PRO_PLAN
    return "free"


def _sub_row(user_id: str) -> dict:
    try:
        r = (admin_client().table("subscriptions")
             .select("plan,status,stripe_customer_id,stripe_subscription_id,current_period_end")
             .eq("user_id", user_id).limit(1).execute())
        return (r.data or [{}])[0]
    except Exception:
        log.exception("subscription lookup failed for %s", user_id)
        return {}


def _email_for(user_id: str) -> str | None:
    try:
        return admin_client().auth.admin.get_user_by_id(user_id).user.email
    except Exception:
        log.warning("could not read email for %s (customer will have no email)", user_id)
        return None


def _user_for_customer(customer_id: str | None) -> str | None:
    if not customer_id:
        return None
    try:
        r = (admin_client().table("subscriptions")
             .select("user_id").eq("stripe_customer_id", customer_id).limit(1).execute())
        return (r.data or [{}])[0].get("user_id")
    except Exception:
        log.exception("customer lookup failed for %s", customer_id)
        return None


@router.get("/status")
def billing_status(user_id: str = Depends(get_current_user)):
    """What the UI needs to decide between "buy Pro" and "Pro isn't open yet".

    Kept separate from /me/limits so the pricing page can render honestly even
    before Stripe keys exist in an environment (prod today).
    """
    row = _sub_row(user_id)
    plan = row.get("plan") or "free"
    return {
        "enabled": stripe_api.enabled(),
        "plan": plan,
        "status": row.get("status") or "active",
        "is_pro": plan in ("premium", "admin"),
        "has_customer": bool(row.get("stripe_customer_id")),
        "prices": {
            "monthly": bool(settings.stripe_price_monthly),
            "annual": bool(settings.stripe_price_annual),
        },
        "grace_days": settings.billing_grace_days,
    }


# ------------------------------------------------------------------ checkout

@router.post("/checkout")
def create_checkout(body: CheckoutBody, user_id: str = Depends(get_current_user)):
    if not stripe_api.enabled():
        raise HTTPException(503, "billing is not configured")
    if body.interval not in ("month", "year"):
        raise HTTPException(422, "interval must be month or year")

    row = _sub_row(user_id)
    if row.get("plan") in ("premium", "admin"):
        # already entitled: send them to the portal rather than selling twice
        if row.get("stripe_customer_id"):
            try:
                return {"url": stripe_api.create_portal_session(row["stripe_customer_id"])["url"]}
            except stripe_api.StripeError as exc:
                raise HTTPException(502, str(exc))
        raise HTTPException(409, "this account already has Pro")

    customer_id = row.get("stripe_customer_id")
    email = _email_for(user_id)
    try:
        if not customer_id:
            customer_id = stripe_api.create_customer(user_id, email)
            quota.set_plan(user_id, row.get("plan") or "free", row.get("status") or "active",
                           stripe_customer_id=customer_id)
        session = stripe_api.create_checkout_session(
            user_id=user_id, customer_id=customer_id, price_id=_price_for(body.interval), email=email)
    except stripe_api.StripeError as exc:
        log.exception("checkout creation failed")
        raise HTTPException(502, str(exc))

    log.info("checkout session %s for %s (%s)", session.get("id"), user_id, body.interval)
    return {"url": session["url"], "session_id": session.get("id")}


@router.post("/portal")
def create_portal(user_id: str = Depends(get_current_user)):
    if not stripe_api.enabled():
        raise HTTPException(503, "billing is not configured")
    customer_id = _sub_row(user_id).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(404, "no billing account yet")
    try:
        return {"url": stripe_api.create_portal_session(customer_id)["url"]}
    except stripe_api.StripeError as exc:
        raise HTTPException(502, str(exc))


# ------------------------------------------------------------------- webhook

def _already_seen(event_id: str, event_type: str | None = None) -> bool:
    """Record the event; True means a previous delivery already applied it."""
    try:
        r = (admin_client().table("stripe_events")
             .insert({"id": event_id, "type": event_type}).execute())
        return not r.data
    except Exception:
        # unique violation = duplicate. Anything else, assume not seen and continue:
        # losing idempotency is better than losing an entitlement change.
        try:
            seen = (admin_client().table("stripe_events").select("id").eq("id", event_id).limit(1).execute())
            return bool(seen.data)
        except Exception:
            log.exception("idempotency check failed for %s", event_id)
            return False


def _apply(event: dict) -> None:
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if kind == "checkout.session.completed":
        user_id = obj.get("client_reference_id")
        customer = obj.get("customer")
        if user_id and customer:
            row = _sub_row(user_id)
            quota.set_plan(user_id, row.get("plan") or "free", row.get("status") or "active",
                           stripe_customer_id=customer)
        return

    if kind.startswith("customer.subscription."):
        sub = obj
        user_id = (sub.get("metadata") or {}).get("user_id") or _user_for_customer(sub.get("customer"))
        if not user_id:
            log.warning("subscription %s has no owning account; ignored", sub.get("id"))
            return

        status = sub.get("status") or "active"
        if kind == "customer.subscription.deleted":
            status = "canceled"
        price_id = (((sub.get("items") or {}).get("data") or [{}])[0].get("price") or {}).get("id")
        plan = _plan_for_price(price_id)

        # Stripe's status vocabulary is wider than ours; map onto the four we enforce
        if status in ("active", "trialing"):
            status = "active" if status == "active" else "trialing"
        elif status in ("past_due", "unpaid", "incomplete_expired"):
            status = "past_due" if status == "past_due" else "canceled"
        elif status == "canceled":
            status = "canceled"

        period_end = sub.get("current_period_end")
        fields = {
            "stripe_customer_id": sub.get("customer"),
            "stripe_subscription_id": sub.get("id"),
        }
        if period_end:
            fields["current_period_end"] = datetime.fromtimestamp(period_end, timezone.utc).isoformat()
        if sub.get("trial_end"):
            fields["trial_end"] = datetime.fromtimestamp(sub["trial_end"], timezone.utc).isoformat()

        quota.set_plan(user_id, plan, status, **fields)
        log.info("subscription %s: %s -> %s/%s", sub.get("id"), user_id, plan, status)
        return

    if kind == "invoice.paid":
        user_id = _user_for_customer(obj.get("customer"))
        if user_id:
            row = _sub_row(user_id)
            fields = {}
            if obj.get("period_end"):
                fields["current_period_end"] = datetime.fromtimestamp(
                    obj["period_end"], timezone.utc).isoformat()
            quota.set_plan(user_id, row.get("plan") or PRO_PLAN, "active", **fields)
        return

    if kind == "invoice.payment_failed":
        user_id = _user_for_customer(obj.get("customer"))
        if user_id:
            row = _sub_row(user_id)
            # keep the plan: quota.py gives a grace window, then withdraws Pro itself
            quota.set_plan(user_id, row.get("plan") or PRO_PLAN, "past_due",
                           current_period_end=row.get("current_period_end"))
        return


@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    try:
        event = stripe_api.verify_webhook(payload, request.headers.get("stripe-signature"))
    except stripe_api.StripeError as exc:
        log.warning("rejected webhook: %s", exc)
        raise HTTPException(400, str(exc))

    event_id = event.get("id")
    if not event_id:
        raise HTTPException(400, "event has no id")
    if _already_seen(event_id, event.get("type")):
        return JSONResponse({"received": True, "duplicate": True})

    try:
        _apply(event)
    except Exception:
        # 500 tells Stripe to retry - the entitlement change must not be silently lost
        log.exception("failed to apply %s", event.get("type"))
        raise HTTPException(500, "could not apply event")
    return {"received": True}
