"""Minimal Stripe client - stdlib only, no SDK.

Three things are needed and nothing else: create a customer, create a Checkout or
Billing Portal session, and verify a webhook signature. Writing them against
`urllib` keeps the dependency list unchanged (this box pins its packages) and
keeps the surface small enough to read in one sitting.

Money is never touched here: Stripe collects cards on its own hosted page, so
nothing in this app ever sees a card number.
"""
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from app.config import settings

log = logging.getLogger("scriber.stripe")

API = "https://api.stripe.com/v1"


class StripeError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.stripe_secret_key)


def _post(path: str, params: dict) -> dict:
    if not enabled():
        raise StripeError("billing is not configured")
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        API + path,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.stripe_secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            err = json.loads(raw).get("error", {})
        except ValueError:
            err = {"message": raw[:200]}
        log.warning("stripe %s failed: %s %s", path, e.code, err.get("message"))
        raise StripeError(err.get("message") or f"stripe error {e.code}")


def _get(path: str, params: dict | None = None) -> dict:
    if not enabled():
        raise StripeError("billing is not configured")
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {settings.stripe_secret_key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise StripeError(f"stripe error {e.code}")


def create_customer(user_id: str, email: str | None) -> str:
    """A customer per account; the user uuid travels in metadata so the webhook can find them."""
    params = {"metadata[user_id]": user_id}
    if email:
        params["email"] = email
    return _post("/customers", params)["id"]


def create_checkout_session(*, user_id: str, customer_id: str | None, price_id: str,
                            email: str | None = None) -> dict:
    """Hosted Checkout in subscription mode.

    Parameters marked "Checkout Studio" come from the Stripe dashboard UI and must
    be sent exactly as configured there. `mode`, `success_url`, `cancel_url` and
    `line_items` are the sample-only ones and carry this app's real values.

    Deliberately kept beyond that list: `client_reference_id` and the subscription
    metadata. They are how the webhook attributes a subscription back to an
    account; without them a payment would take money and grant nothing.
    """
    params = {
        # --- Checkout Studio (configured in the dashboard, do not hand-edit) ---
        "ui_mode": "hosted_page",
        "billing_address_collection": "auto",
        "phone_number_collection[enabled]": "true",
        "allow_promotion_codes": "true",
        "payment_method_collection": "always",
        "submit_type": "auto",
        "integration_identifier": "hosted_web_0001",
        "origin_context": "web",
        # --- sample-only, real values for this app ---
        "mode": "subscription",
        "success_url": f"{settings.app_base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{settings.app_base_url}/pro",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        # --- attribution (see STRIPE_INTEGRATION_TODO.md) ---
        "client_reference_id": user_id,
        "subscription_data[metadata][user_id]": user_id,
    }
    # Stripe Tax needs a head-office address on the account; until that exists
    # every session fails with "valid head office address" - so it is switchable.
    if settings.stripe_automatic_tax:
        params["automatic_tax[enabled]"] = "true"
    if customer_id:
        params["customer"] = customer_id
    elif email:
        params["customer_email"] = email
    return _post("/checkout/sessions", params)


def create_portal_session(customer_id: str) -> dict:
    """Billing Portal: card updates, invoices, cancellation - all hosted by Stripe."""
    return _post("/billing_portal/sessions", {
        "customer": customer_id,
        "return_url": f"{settings.app_base_url}/pro",
    })


def retrieve_subscription(subscription_id: str) -> dict:
    return _get(f"/subscriptions/{subscription_id}")


# --------------------------------------------------------------- webhooks

def verify_webhook(payload: bytes, signature_header: str | None, tolerance_s: int = 300) -> dict:
    """Verify a Stripe-Signature header and return the parsed event.

    Scheme: `t=<unix>,v1=<hex hmac>` over b"<t>.<payload>", HMAC-SHA256 with the
    endpoint secret. The timestamp check is what stops a captured request being
    replayed later.
    """
    secret = settings.stripe_webhook_secret
    if not secret:
        raise StripeError("webhook secret is not configured")
    if not signature_header:
        raise StripeError("missing Stripe-Signature header")

    ts = None
    sigs = []
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k == "t":
            ts = v
        elif k == "v1":
            sigs.append(v)
    if ts is None or not sigs:
        raise StripeError("malformed signature header")

    try:
        if abs(time.time() - int(ts)) > tolerance_s:
            raise StripeError("timestamp outside tolerance")
    except ValueError:
        raise StripeError("bad timestamp")

    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise StripeError("no matching signature")

    return json.loads(payload.decode())
