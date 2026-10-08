# Scribly Master Task List (Oct 1, 2026)

Reference IDs: `W16-*` = launch/domain, `F-*` = features, `T-*` = tiers/monetization, `E-*` = environments, `O-*` = ops/hardening. Detailed tier notes: `scribly-tiers-launch.md` (same dir).

## Launch / Domain (W16)
- **W16-1** DNS at Cloudflare: `scribly.cc` → home entry point; decide subdomains (`app.scribly.cc` for the app, root for landing)
- **W16-2** NPM proxy host + Let's Encrypt cert for `scribly.cc` / `app.scribly.cc`
- **W16-3** DECISION before launch: POC (pocscribly) currently shares the production Supabase on 201 — separate DB/project per environment (see E-1) before exposing to real users
- **W16-4** Replace `.local` test accounts with real user accounts; keep `test@` only in dev
- **W16-5** Landing page for scribly.cc (marketing, separate from app)
- **W16-6** app.scribly.cc 1.0 launch (typo'd "sribly" in original notes)
- **W16-7** ToS / privacy policy (video storage, auto-deletion, watermarked exports)

## Features (F)
- **F-1** Embedded-subtitle render + download — ffmpeg `subtitles` burn-in, server-side; watermark on free (T-tier coupling)
- **F-2** Subtitle editing UI — edit segment text in-app before export/render
- **F-3** Upload video menu / dedicated upload flow (incl. bulk upload for premium, T-8)
- **F-4** Watermark toggle for premium
- **F-5** Email setup: `*@scribly.cc` addresses, SMTP provider, GoTrue verification + password reset (`MAILER_AUTOCONFIRM=false`) — required for T-2 email capture
- **F-6** Transcode pipeline (NEW, biggest hidden item): ffmpeg CPU jobs for free 240p compression / premium 720p auto-compress; sized ~tens of min CPU per hour of video
- **F-7** Quota tracking schema: per-user counters (transcriptions/day, diarizations/day, upload bytes) + sliding windows (50 per 12h for premium)
- **F-8** Queue priority: `high`/`low` RQ queue pairs, enqueue by tier
- **F-9** Auto-delete job: daily sweep, free videos >7 days old; delete segments, thumbs, artifacts; handle in-flight jobs
- **F-10** Free-tier countdown timer on video page (days until auto-delete)

## Features (F) — added Oct 1, 2026 (session decisions)
- **F-11** Browser web-push notifications: service worker + VAPID, replaces ntfy for browser users (HTTPS-only — works on pocscribly/scribly.cc, NOT on LAN HTTP); ntfy stays for phone
- **F-12** Cross-chunk speaker continuity — **cheap approximation chosen (option 3)**: run pyannote once on a heavily-downsampled single pass to get the global speaker grouping, use it as the label map to remap chunk-local labels before writing segments. (Replaces per-chunk naive labels found in O-4 — dominant speaker currently rotates between 20-min windows on the WAN Show.)

## Tiers / Monetization (T)
- **T-1** Stripe setup: products (Free/Premium), checkout, webhook receiver endpoint
- **T-2** Email capture gate: free plan = 1 transcription/day, requires verified email (depends F-5)
- **T-3** `subscriptions` table: user_id, plan, trial_end, current_period_end; enforcement reads it
- **T-4** Trial: 14-day Stripe-native trial; premium limits during trial? decide
- **T-5** Free limits: 15 min video length (single limiter — length, not size), 500 MB implicit, 1-day share-link expiry, no diarization, no bulk, low priority, watermark everywhere
- **T-6** Premium limits: 5 GB upload (single limiter — size), 30-day share links, no auto-delete, 24 h length, diarization 10/day, bulk upload, high priority, no watermark (toggleable, F-4)
- **T-7** Marketing consistency: implement premium as 50-per-12h sliding window even if page says "100/day"
- **T-8** Bulk upload UI (premium only)

## Environments (E)
- **E-1** Dev + prod split: separate Supabase project/DB, API instance, frontend deploy, Stripe test vs live keys (blocks W16-3; do before any paid work)

## Ops / Hardening (O)
- **O-1** NPM conf fragility: studio-403 allowlist (conf 21) + `/sb` route (conf 20) live in raw files the NPM UI will wipe on edit — move to Advanced/custom locations or document re-apply steps
- **O-2** Disk bump 204/205: 20 GB → 32 GB (venv 5.9 GB and creeping)
- **O-3** Remove old `/sb` route on pocscribly host (fallback no longer needed — frontend uses db.scribly.cc)
- **O-4** W10 follow-up: verify WAN Show chunked-diarize quality (cross-chunk speaker-label continuity is still naive)
- **O-5** Confirm ntfy push fires on diarize completion (transcribe has it)
- **O-6** Refresh docs/user-guide + README for v0.7.x reality (share links, diarization toggle, dual download modes, db.scribly.cc topology)
- **O-7** Benchmarks doc: add int8 P4 numbers from W10 runs

## Suggested order (dependency-driven)
1. E-1 (env split) → 2. F-5 (email) → 3. W16-1/2 (DNS+cert) → 4. F-6/F-7 (transcode+quota, biggest build) → 5. T-1..T-8 (Stripe+tiers on top) → 6. F-1..F-4, F-9/10 (watermark, editing, auto-delete) → 7. W16-5..7 (landing, launch, legal)
