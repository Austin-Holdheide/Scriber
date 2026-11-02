"""T-1 billing rules - no network, no database.

Two things are worth pinning here because getting them wrong costs money or
locks a paying customer out:

  - which Stripe price buys which plan (a typo silently sells nothing)
  - the webhook signature check (an unchecked endpoint lets anyone grant Pro)
  - the past_due grace window (a failed card must not end access instantly)
"""
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers import billing
from app.services import quota, stripe_api


# ------------------------------------------------------------------ price -> plan

def test_known_prices_buy_premium(monkeypatch):
    monkeypatch.setattr(settings, "stripe_price_monthly", "price_monthly", raising=False)
    monkeypatch.setattr(settings, "stripe_price_annual", "price_annual", raising=False)
    assert billing._plan_for_price("price_monthly") == "premium"
    assert billing._plan_for_price("price_annual") == "premium"


def test_unknown_prices_do_not_buy_premium(monkeypatch):
    monkeypatch.setattr(settings, "stripe_price_monthly", "price_monthly", raising=False)
    monkeypatch.setattr(settings, "stripe_price_annual", "price_annual", raising=False)
    assert billing._plan_for_price("price_someone_elses") == "free"
    assert billing._plan_for_price(None) == "free"
    assert billing._plan_for_price("") == "free"


def test_unconfigured_billing_refuses_checkout(monkeypatch):
    monkeypatch.setattr(settings, "stripe_price_monthly", "", raising=False)
    monkeypatch.setattr(settings, "stripe_price_annual", "", raising=False)
    with pytest.raises(HTTPException) as exc:
        billing._price_for("month")
    assert exc.value.status_code == 503


def test_interval_picks_the_right_price(monkeypatch):
    monkeypatch.setattr(settings, "stripe_price_monthly", "price_m", raising=False)
    monkeypatch.setattr(settings, "stripe_price_annual", "price_a", raising=False)
    assert billing._price_for("month") == "price_m"
    assert billing._price_for("year") == "price_a"
    assert billing._price_for("weekly") == "price_m"   # anything not "year" is monthly


# ------------------------------------------------------------------ grace window

def _stamp(days_ago: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_past_due_keeps_the_plan_inside_the_grace_window(monkeypatch):
    monkeypatch.setattr(settings, "billing_grace_days", 7, raising=False)
    assert quota.in_billing_grace({"updated_at": _stamp(1)}) is True
    assert quota.in_billing_grace({"updated_at": _stamp(6)}) is True


def test_past_due_lapses_after_the_grace_window(monkeypatch):
    monkeypatch.setattr(settings, "billing_grace_days", 7, raising=False)
    assert quota.in_billing_grace({"updated_at": _stamp(9)}) is False


def test_zero_grace_means_immediate(monkeypatch):
    monkeypatch.setattr(settings, "billing_grace_days", 0, raising=False)
    assert quota.in_billing_grace({"updated_at": _stamp(0)}) is False


def test_unknown_age_keeps_the_customer_working(monkeypatch):
    monkeypatch.setattr(settings, "billing_grace_days", 7, raising=False)
    assert quota.in_billing_grace({}) is True


def test_plan_lookup_applies_the_grace_rule(monkeypatch):
    """past_due + fresh -> premium; past_due + stale -> free; canceled -> free."""
    rows = {
        "fresh": {"plan": "premium", "status": "past_due", "updated_at": _stamp(2)},
        "stale": {"plan": "premium", "status": "past_due", "updated_at": _stamp(30)},
        "gone":  {"plan": "premium", "status": "canceled",  "updated_at": _stamp(0)},
    }
    monkeypatch.setattr(settings, "billing_grace_days", 7, raising=False)

    class FakeQuery:
        def __init__(self, row): self.row = row
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": [self.row]})()

    class FakeClient:
        def table(self, _): return FakeQuery(current[0])
    current = [rows["fresh"]]
    monkeypatch.setattr(quota, "admin_client", lambda: FakeClient())

    assert quota.plan_name_for("u") == "premium"
    current[0] = rows["stale"]
    assert quota.plan_name_for("u") == "free"
    current[0] = rows["gone"]
    assert quota.plan_name_for("u") == "free"


# ------------------------------------------------------------------ webhook auth

def _sign(payload: bytes, secret: str, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_valid_signature_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test", raising=False)
    payload = json.dumps({"id": "evt_1", "type": "invoice.paid"}).encode()
    assert stripe_api.verify_webhook(payload, _sign(payload, "whsec_test"))["id"] == "evt_1"


def test_wrong_secret_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test", raising=False)
    payload = b'{"id":"evt_1"}'
    with pytest.raises(stripe_api.StripeError):
        stripe_api.verify_webhook(payload, _sign(payload, "whsec_other"))


def test_tampered_payload_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test", raising=False)
    payload = b'{"id":"evt_1","amount":900}'
    sig = _sign(payload, "whsec_test")
    with pytest.raises(stripe_api.StripeError):
        stripe_api.verify_webhook(b'{"id":"evt_1","amount":1}', sig)


def test_stale_timestamp_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test", raising=False)
    payload = b'{"id":"evt_1"}'
    old = int(time.time()) - 3600
    with pytest.raises(stripe_api.StripeError):
        stripe_api.verify_webhook(payload, _sign(payload, "whsec_test", ts=old))


def test_missing_header_or_secret_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test", raising=False)
    with pytest.raises(stripe_api.StripeError):
        stripe_api.verify_webhook(b"{}", None)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "", raising=False)
    with pytest.raises(stripe_api.StripeError):
        stripe_api.verify_webhook(b"{}", "t=1,v1=deadbeef")
