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
3. **T-1c Legal sign-off** — checkout-era `terms.html` / `privacy.html` exist on the branch (prices,
   auto-renewal, cancellation, refunds, 7-day grace, processor table) but are **not deployed**; prod still
   serves the Oct-29 copy. The refund wording is a draft — it needs your approval before it goes live.
4. **T-1d Live keys** — live-mode prices, `sk_live_`, a live webhook endpoint at
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
4. **F-7b Hour-based metering.** `usage_events` counts transcriptions, not audio hours; "fair use" is
   policy with no measurement. Add `duration_s` to the event and sum it for reporting and throttling.
5. Then product depth, biggest first: **F-6 transcode** (free 240p / Pro 720p, CPU ffmpeg jobs — the
   largest remaining build), **F-1 burn-in subtitles**, **F-4 watermark toggle**, **F-3/T-8 bulk upload**
   and a dedicated upload page.
6. **Ship the queue lanes to prod.** Code is on dev and verified; prod 202–205 still run the single
   `transcribe-gpu` lane. Drain check then rollout order are in `docs/runbook.md` ("Rolling the lanes
   to prod"). Do it *before* taking real money: the whole point is that a paid upload is not queued
   behind free traffic.

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
- **O-9** Prove CI actually runs. `.github/workflows/ci.yml` ships on `feature/billing-stripe` only and
  GitHub reports **0 workflow runs**, so every check so far has been run by hand. After the merge, confirm a
  green run on a throwaway PR before trusting it as a gate.

## Automation and self-checks (A) — proposed 2026-11-18

Goal: know the product works, not just that the units are `active`. Everything below is additive to
what already exists — do not rebuild those parts.

**Already running (leave alone):** ten Grafana rules → `grafana-ntfy-relay` → ntfy `scriber-alerts` →
phone (API down, worker down, worker restart loop, queue backlog, failed jobs, disk > 80 %, GPU wedged,
GPU temp, exporter down, node down); `scriber-requeue.timer` every 60 s on 202 (stale-job requeue +
cancel convergence); media ZFS snapshot 03:15 daily; offsite copy Sun 05:00; vzdump nightly 04:00;
`hermes-autoupdate.timer` 04:30.

**The gap, verified:** every existing rule watches a unit, a socket or a metric. Nothing proves an
upload becomes a transcript. A worker can be `active` with a broken model, Cloudflare can refuse POSTs,
a migration can break the DB trigger, or the storage bind can vanish — and the first sign is a user
telling us. Dev (206) is not scraped at all. Backup *freshness* is unmonitored: a silently failing
`pg_dump` looks exactly like a healthy one until a restore is needed.

- **A-1 Synthetic canary (highest value).** Every 15 min: a dedicated canary account uploads a generated
  5-second MP4 (ffmpeg `testsrc` + sine) through the **public** hostname, waits ≤ 10 min for
  `videos.status=done` with segments > 0, then hard-deletes video + media. Exports
  `scriber_canary_ok`, `scriber_canary_seconds`, `scriber_canary_last_success_timestamp`. Alert on 2
  consecutive failures, or no success in 45 min. One probe covers API + JWKS + Cloudflare + Supabase +
  Redis + lane routing + GPU + whisper + storage + thumbnails + the delete path. Canary account is
  `admin` plan and excluded from usage/retention so it never pollutes the counters or the sweep (F-9).
- **A-2 Freshness alerts.** pg_dump age > 26 h, media snapshot > 26 h, offsite > 8 days, vzdump > 26 h,
  canary last-success > 45 min. Cheap Prometheus rules over file mtimes (`node_exporter` textfile
  collector) — the failure they catch is silent by nature.
- **A-3 Dev under monitoring.** Scrape 206 (node + app exporter + its lane depths) and run a dev canary,
  so a regression is caught on `dev.scribly.cc` instead of by eye.
- **A-4 Scoped self-healing — only for failure modes already known.** (a) reconcile the RQ worker
  registry against live PIDs and clear the stale `rq:worker:` key that crash-loops a restarted unit;
  (b) restart a worker whose RQ heartbeat is older than 3× the interval while its unit is `active`;
  (c) restart Supabase containers after 3 failed health calls, with backoff, max 2/hour. Rule: every
  automatic action also sends a notification — never heal silently, that is how the cause gets lost.
- **A-5 Prove the alarm path, and drill the restore.** Hourly heartbeat published to ntfy and alerted on
  when it stops (an alerting chain that dies quietly is worse than none); monthly restore of the newest
  pg_dump into a scratch database with row counts compared; intentional stop of a worker on dev to
  confirm FIRING + RESOLVED still reach the phone after any routing change.

**Order:** A-1 + A-2 first (cheap, and together they cover "is it working" and "is the data safe"), then
A-3, then A-4 restricted to those three modes, A-5 as standing practice.

## Done ledger (newest first)

- **F-8 Queue priority lanes (2026-11-18, dev only).** `quota.lane_for_plan/lane_for_user` decide the
  lane; uploads land in `transcribe-high` (premium/admin) or `transcribe-low` (free), and workers read
  `high` first. Proven on 206: worker logged `listening on transcribe-high, transcribe-low`, then with
  both queues pre-loaded (free enqueued first) the parent process dequeued **high before low**, and
  `RCPT`-style per-lane `LLEN` confirmed each job landed in its own queue. 82 tests pass, including
  `tests/test_queue_lanes.py` (unknown/missing plans fall to the free lane; `ingest.finalize_upload`
  passes the plan's lane; legacy `RQ_QUEUE` cannot outrank a lane). Prod 202–205 still single-lane.
  Requeue sweeper and re-transcribe carry the lane too, so a requeued Pro job does not drop to free.

- **Email routing live (F-5b, 2026-11-18).** Cloudflare Email Routing on `scribly.cc`: MX ×3
  (`route1/2/3.mx.cloudflare.net`), the null SPF `v=spf1 -all` replaced by
  `v=spf1 include:_spf.mx.cloudflare.net -all` (one record only — two SPF records is a permerror, which
  is what the dashboard wizard leaves behind), `cf2024-1._domainkey` DKIM, and rules for
  `hello@scribly.cc` + `privacy@scribly.cc` → the verified destination `austin.holdheide@outlook.com`.
  Proven with `RCPT TO` returning `250 2.1.0 Ok` at all three MXs, then two real messages through Resend.
  Resend was unaffected: it authenticates on `send.scribly.cc` + `resend._domainkey`, not the apex.
  Tooling: `/root/.hermes/cf_email_routing.py` (idempotent, `--apply`; aborts before touching DNS if
  enabling routing fails).

- `5dfbedd` Checkout Studio parameters + `STRIPE_AUTOMATIC_TAX` switch, verified against the live test
  account (nine parameters stored, `amount_total` 900 usd, 61 tests).
- `964d155` CI: `scripts/audit.py` (plan-number/copy/markup/palette/secrets consistency) + pytest + tsc/vite
  on every push; first run caught a forbidden emoji and an off-palette colour. **Caveat: GitHub has never
  executed it — 0 workflow runs on the repo, because `ci.yml` exists only on this branch.** It starts
  gating for real once the file is on `main`.
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
