# Scribly — master task list

**Last verified against the live stack: 2026-11-18.** This file is the single backlog. Where an older
plan (`docs/status.md`, `docs/tiers-plan.md`, `/root/.hermes/plans/*`) disagrees, this file wins — those
are point-in-time notes. ID scheme is unchanged: `W16-*` launch, `F-*` features, `T-*` tiers,
`E-*` environments, `O-*` ops.

Shipped history lives in `CHANGELOG.md`; operational rules and traps in `HANDOFF.md`.

## Live state, verified 2026-11-18

| | State |
|---|---|
| Prod app | `https://app.scribly.cc` → 202, health 200. Frontend build **2026-10-29 20:25** (v0.8.0 + chunked uploads). **No Stripe env, no `stripe_events` table** |
| Landing | `https://scribly.cc` → 202 `/var/www/landing`, index 2026-10-29, terms/privacy 2026-10-29 (pre-billing wording) |
| Dev | `https://dev.scribly.cc` → 206, health 200. Frontend build **2026-11-04 18:27**; `0009` applied; Stripe **test** keys set; `STRIPE_AUTOMATIC_TAX=0`. 61 tests green |
| Billing code | `feature/billing-stripe` @ `5dfbedd`, clean, pushed, **7 commits ahead of `main`** — not merged, not on prod |
| Workers | 203 redis + `rq-worker@203` + Prometheus + ntfy + relay; 204/205 GPU workers, both active |
| Backups | media ZFS snapshot daily 03:15, pg_dump daily → `/neoDATA/media/pg`, offsite weekly Sun 05:00, vzdump nightly 04:00 |
| DNS | `scribly.cc`, `app.`, `dev.`, `ntfy.` all 200. **No MX**, SPF `v=spf1 -all`. `pocscribly.holdheide.com` retired (no record) |
| Disk | 205 rootfs **69%** (20 G), 204 49%, 203 35%, 206 40% (32 G) |

## Blocked on the operator — no code left on our side

1. **T-1a Stripe onboarding** — `details_submitted: false`, `charges_enabled: false`, `business_type: null`.
   Business type, bank account, product description, industry, statement descriptor `SCRIBLY`.
   Nothing can charge a real card until this is done.
2. **T-1b Head-office address** — with `automatic_tax` on, every Checkout session is rejected with
   *"You must have a valid head office address"*. Dev is parked at `STRIPE_AUTOMATIC_TAX=0` so the flow can
   be exercised. **Flip to `1` the moment the address is saved** — selling with no tax calculation is not
   a place to sit.
3. **F-5b Email routing** — `hello@scribly.cc` and `privacy@scribly.cc` are printed on the public pages but
   the zone has no MX and SPF is `v=spf1 -all`, so mail is refused. Cloudflare Email Routing + SPF merge to
   `v=spf1 include:_spf.mx.cloudflare.net -all`. Needs a Zone.DNS API token, or four dashboard clicks.
4. **T-1c Legal sign-off** — checkout-era `terms.html` / `privacy.html` exist on the branch (prices,
   auto-renewal, cancellation, refunds, 7-day grace, processor table) but are **not deployed**; prod still
   serves the Oct-29 copy. The refund wording is a draft — it needs your approval before it goes live.
5. **T-1d Live keys** — live-mode prices, `sk_live_`, a live webhook endpoint at
   `https://app.scribly.cc/api/billing/webhook` + its signing secret, then the same on dev for test mode.

## Next — code, in the order I would do it

1. **T-1e Billing to prod, safe now.** Apply `migrations/0009_stripe_billing.sql`, push the billing code
   and rebuild the frontend on 202. With no Stripe keys present, `GET /api/billing/status` reports
   *not configured* and `/pro` keeps the early-access list, so prod behaviour is unchanged until keys land
   (this is exactly why the UI is gated on the endpoint, not a build flag). Merge `feature/billing-stripe`
   → `main` after you have looked at dev.
2. **F-9 Auto-delete sweep (7-day free retention).** `quota.py` already declares `retention_days=7` for
   free, but **no sweep exists** — the landing page promises deletion we do not perform. Needs: cutoff date
   so the existing prod test library is not nuked, dry-run mode, artifact + media cleanup mirroring
   `videos_delete.py`, and the in-flight-job guard.
3. **F-10 Countdown timer on the video page** (free accounts: days until auto-delete). Ships with F-9 —
   meaningless before it.
4. **F-8 Queue priority lanes.** `Plan.queue` is `low`/`high` in `quota.py`, but `services/queue.py`
   enqueues everything to the single `transcribe-gpu` queue, so **Pro buys no priority today**.
   Wire `high`/`low` pairs in `enqueue_transcription` and have workers listen on both.
5. **F-7b Hour-based metering.** `usage_events` counts transcriptions, not audio hours; "fair use" is
   policy with no measurement. Add `duration_s` to the event and sum it for reporting and throttling.
6. Then product depth, biggest first: **F-6 transcode** (free 240p / Pro 720p, CPU ffmpeg jobs — the
   largest remaining build), **F-1 burn-in subtitles**, **F-4 watermark toggle**, **F-3/T-8 bulk upload**
   and a dedicated upload page.

## Backlog

**Features**
- **F-11** Browser web-push (service worker + VAPID). Nothing built; ntfy covers phone only, and the app
  never tells a browser user their job finished.
- **F-3** Dedicated upload flow / drop page. Today upload is a drag-and-drop inside the library.
- **F-2** ~~Subtitle editing UI~~ **DONE** — inline `PATCH /api/segments/{id}` editing in the viewer.
- **F-5** SMTP/Resend verification + reset **DONE**; only the MX/SPF half is open (item 3 above).

**Tiers / marketing consistency**
- **T-4** ~~14-day trial~~ **DECIDED: no trial.** `landing/index.html` FAQ says "it is not a trial" and
  Checkout sends no `trial_period_days`. `billing.py` still understands a Stripe `trialing` status, which
  is correct — it just is not something we create. Do not resurrect the trial without changing the copy.
- **T-5 / T-6** Limits as shipped match `quota.py` (free 15 min / 500 MB / 1 per 24 h / no diarization /
  7-day shares; Pro 5 GB / 24 h / diarization 10/day / 30-day shares / unlimited transcriptions under fair
  use). **Watermark on free is NOT built**, so no tier is watermarked yet.
- **T-7** ~~50-per-12 h sliding window~~ **superseded**: Pro sells "unlimited" and `QUOTA_PREMIUM_UPLOADS`
  defaults to `-1`; the terms carry the fair-use clause. Audit script keeps copy and `quota.py` in sync.
- **T-8** Bulk upload UI (Pro only) — not built.

**Environments**
- **E-1** Dev/prod split: phase 1 done (206 with own Supabase/Redis/media/frontend). Remaining: dev
  Prometheus job for 206, and a written dev-first migration rule (currently convention only: 0009 is on dev,
  not prod). Note dev media has **no snapshots** — the 2026-10-29 wipe is unrecoverable by design.
- **W16-3** POC sharing prod Supabase — moot: `pocscribly.holdheide.com` no longer resolves.
- **W16-4** Test/`.local` accounts in prod Supabase still to be removed; `test@scriber.local` belongs in dev only.

**Ops / hardening**
- **O-1** NPM raw-conf fragility: studio-403 allowlist (conf 21) and the legacy `/sb` route (conf 20) live
  in files the NPM UI rewrites on edit. Move them to Advanced/custom locations or document re-apply steps.
- **O-2** Disk bump 204/205 20 G → 32 G. 205 is at **69%** now; this is the next one to bite.
- **O-3** Remove the `/sb` route (the frontend uses `db.scribly.cc`). Tied to O-1.
- **O-4** ~~WAN Show diarization quality~~ **superseded by F-12** (global re-clustering, verified 3 h 42 m).
- **O-5** ntfy push on diarize completion — `diarize_tasks.py` calls `notify`, so it exists on dev; still
  needs one end-to-end proof on a real diarized job.
- **O-6** README / user-guide refresh for v0.8.x reality (share links, diarization, dual download modes,
  `db.scribly.cc` topology, chunked upload).
- **O-7** `docs/benchmarks.md`: add the int8 P4 numbers from the W10 runs.
- **O-8** RQ worker health is unit-level (`node_systemd_unit_state`), not RQ-level: a live unit holding a
  stale `rq:worker:` key is only caught while systemd retries. Consider an RQ-level exporter.

## Done ledger (newest first)

- `5dfbedd` Checkout Studio parameters + `STRIPE_AUTOMATIC_TAX` switch, verified against the live test
  account (nine parameters stored, `amount_total` 900 usd, 61 tests).
- `964d155` CI: `scripts/audit.py` (plan-number/copy/markup/palette/secrets consistency) + pytest + tsc/vite
  on every push; first run caught a forbidden emoji and an off-palette colour.
- `bdcfcc1`…`560fe84` brand assets (icon/mark/wordmark PNGs Stripe wants, palette + measured contrast).
- `443fc4a` Billing UI: `/pro` three-state CTA, `BillingSuccess`, drafted terms/privacy.
- `5699beb` Stripe Checkout + Billing Portal + webhook (T-1), `0009_stripe_billing.sql`.
- `ec37aa3` chunked-upload resume fix (partial part tail discarded before retry).
- `c9432c4` nine alert rules as code (`ops/grafana-alerts/`), proven firing + resolved.
- **v0.8.0** (2026-11-02): Scriber → Scribly rebrand, `scribly.cc` + `app.scribly.cc` + `db.scribly.cc`,
  landing site, verified signups + Resend mail + reset, `subscriptions`/`usage_events` with free enrolment
  trigger, enforcement 429/413/422/402, `/api/me/limits|plan|interest`, plan line + upgrade prompt,
  64 MiB chunked uploads, pyannote 3.1 diarization in 10-minute chunks, F-12 global speaker re-clustering,
  Grafana → ntfy alerting, share links, FTS search, SRT/VTT/TXT/DOCX/PDF exports.
