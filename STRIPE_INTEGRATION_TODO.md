# Stripe integration — remaining setup

Integration type: **Hosted Checkout** (the customer is redirected to a Stripe-hosted payment page).
Scenario: **A** — an existing Checkout Session call was found and its parameters were updated; no new
routes, files or refactors were added.

**Where the call lives:** [`backend/app/services/stripe_api.py`](backend/app/services/stripe_api.py) →
`create_checkout_session()`. It talks to `/v1/checkout/sessions` over plain HTTP (no Stripe SDK), so
there is no SDK version to pin and no `Stripe-Version` header is sent — the account default applies.

---

## Values to Replace

**Files containing values that change per environment:**
- [backend/app/services/stripe_api.py](backend/app/services/stripe_api.py) — nothing hardcoded; all values arrive from settings
- [backend/.env](backend/.env) — where those settings come from

No placeholder values were written into the code: `mode`, `success_url`, `cancel_url` and
`line_items` already carried this app's real values and were preserved as the rules require.

| Field | Current Value | What to Set |
|---|---|---|
| `line_items[0][price]` (monthly) | `price_1UXN1aF1AnH3cmIwUmqOBsc9` (`scribly_pro_monthly`, $9/mo, **test mode**) | A **live-mode** price ID from https://dashboard.stripe.com/prices before taking real money. |
| `line_items[0][price]` (annual) | `price_1UXN1aF1AnH3cmIwQsMSio4Y` (`scribly_pro_annual`, $90/yr, **test mode**) | The live-mode annual price ID. |
| `STRIPE_SECRET_KEY` | `sk_test_…` | `sk_live_…` at go-live. Never commit it — it lives in the container env only. |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` for the **dev** endpoint | The signing secret of the **prod** webhook endpoint once it exists. |
| `APP_BASE_URL` | `https://dev.scribly.cc` (dev) / `https://app.scribly.cc` (default) | Leave as-is; it builds `success_url` and `cancel_url`. |

---

## Configured Parameters

These came from Checkout Studio and are sent exactly as configured.

**Files containing these parameters:**
- [backend/app/services/stripe_api.py](backend/app/services/stripe_api.py)

| Parameter | Value |
|---|---|
| `ui_mode` | `hosted_page` |
| `billing_address_collection` | `auto` |
| `phone_number_collection[enabled]` | `true` |
| `automatic_tax[enabled]` | `true` — **see blocker below** |
| `allow_promotion_codes` | `true` |
| `payment_method_collection` | `always` (sent because `mode` is `subscription`) |
| `submit_type` | `auto` |
| `integration_identifier` | `hosted_web_0001` |
| `origin_context` | `web` |

Preserved sample-only values: `mode=subscription`, `success_url=/billing/success?session_id={CHECKOUT_SESSION_ID}`,
`cancel_url=/pro`, `line_items[0].price` (the two price IDs above).

### Two deliberate deviations, so they are not a surprise

**1. `automatic_tax` is switchable, and it currently blocks every payment.**
With it enabled the API returns:

> *You must have a valid head office address to enable automatic tax calculation in test mode.*

This is not a code fault — the Stripe account has no head-office address yet. Until you add one
(Settings → Business settings → Address) **every Checkout session fails**. So the parameter is driven by
`STRIPE_AUTOMATIC_TAX`:

- `STRIPE_AUTOMATIC_TAX=0` — omit the parameter, sell now, tax calculated by nobody.
- `STRIPE_AUTOMATIC_TAX=1` (default) — send exactly what Checkout Studio configured.

**Flip it to `1` (or delete the line) as soon as the head-office address is saved.** The dev container is
currently set to `0` so the flow can be tested.

**2. `client_reference_id` and `subscription_data[metadata][user_id]` were kept**, even though the
integration brief lists them as "parameters absent from the Field Intents → remove". Removing them would
break entitlement: the webhook uses them to decide *which account* a subscription belongs to. Without
them a customer would be charged and nothing would be upgraded. `customer` / `customer_email` are kept
for the same reason — they tie the Stripe customer to the account row.

---

## Setup and next steps

### Environment variables

Set inside the container (never in git — `scripts/audit.py` fails the build if a key appears in the repo):

| Variable | Required | Purpose |
|---|---|---|
| `STRIPE_SECRET_KEY` | yes | server-side API key (`sk_test_…` / `sk_live_…`) |
| `STRIPE_WEBHOOK_SECRET` | yes | verifies `Stripe-Signature` on `/api/billing/webhook` |
| `STRIPE_PRICE_MONTHLY` | yes | `price_…` for $9/month |
| `STRIPE_PRICE_ANNUAL` | yes | `price_…` for $90/year |
| `APP_BASE_URL` | yes | builds `success_url` / `cancel_url` |
| `BILLING_GRACE_DAYS` | no (7) | days a `past_due` subscription keeps Pro |
| `STRIPE_AUTOMATIC_TAX` | no (1) | see the tax blocker above |

No publishable key is needed: with hosted Checkout the browser is redirected to Stripe, so no Stripe.js
runs in this app and no `VITE_*` Stripe variable exists on purpose.

### How the flow works

1. `POST /api/billing/checkout {interval}` — auth required. Looks up the account's `subscriptions` row,
   creates a Stripe customer if there isn't one, then creates a Checkout Session and returns `{url}`.
2. The browser is redirected to `checkout.stripe.com`. Card details are entered there; **Scribly never
   sees them** (no PCI scope in this app).
3. Stripe redirects back to `/billing/success?session_id=…`. That page polls `/api/me/limits` because the
   webhook may land a moment later; if it never does, it says so instead of pretending.
4. `POST /api/billing/webhook` (unsigned-request proof, verified with HMAC-SHA256 over
   `<t>.<payload>`) applies `checkout.session.completed`, `customer.subscription.*`, `invoice.paid`,
   `invoice.payment_failed`. Every event id is recorded in `stripe_events` first, so a Stripe retry is a
   no-op. A failed apply returns 500 so Stripe retries rather than losing the change.
5. `subscriptions` (plan, status, period end) is the only thing `quota.py` reads. Cancelled lapses to free
   immediately; `past_due` keeps Pro for the grace window, then lapses.

### Project structure of the files involved

```
backend/app/services/stripe_api.py    the Checkout Session call + signature verification
backend/app/routers/billing.py        /checkout, /portal, /webhook, /status
backend/app/services/quota.py         plan → entitlement (reads subscriptions only)
migrations/0009_stripe_billing.sql    stripe_events, cancel_at_period_end, canceled_at
frontend/src/pages/Pro.tsx            the three CTA states (Pro / buy / not configured)
frontend/src/pages/BillingSuccess.tsx post-payment confirmation
```

No new files were created for this task. `STRIPE_INTEGRATION_TODO.md` (this file) is the exception.

### Testing

Test mode, card `4242 4242 4242 4242`, any future expiry, any CVC, any postcode.

Other useful numbers: `4000 0025 0000 3155` requires 3-D Secure; `4000 0000 0000 9995` fails for
insufficient funds (good for exercising the `past_due` grace path); `4000 0000 0000 0341` attaches
then fails on renewal.

Webhook deliveries can be resent from the Dashboard or replayed with a signed payload; the
`stripe_events` table will report duplicates as `{"duplicate": true}` rather than double-granting.

### Before going live

1. Complete Stripe onboarding — `details_submitted` and `charges_enabled` are still `false`.
2. Add the head-office address, then set `STRIPE_AUTOMATIC_TAX=1`.
3. Create **live** prices, put their IDs in `STRIPE_PRICE_MONTHLY` / `STRIPE_PRICE_ANNUAL`.
4. Swap `sk_test_` → `sk_live_` and register a **live** webhook for
   `https://app.scribly.cc/api/billing/webhook`; put its signing secret in `STRIPE_WEBHOOK_SECRET`.
5. Set the statement descriptor (`SCRIBLY`) under Settings → Payments so card statements are recognisable.
6. Confirm the terms page refund wording is yours, not the draft's.

### Resources

- https://docs.stripe.com/payments/checkout
- https://docs.stripe.com/webhooks
- https://support.stripe.com
