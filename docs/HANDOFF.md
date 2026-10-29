# Handoff — state of Scribly, 2026-10-29

Read this first. It supersedes older plan docs where they disagree.

## Where everything lives

| Thing | Location |
|---|---|
| Repo (branch `main`) | `/root/git/Scriber` — also `/root/projects/scribly` (workspace docs) |
| Prod app | `https://app.scribly.cc` → CT **202** (`transcriber-api` :8001, Caddy, frontend `/opt/scriber/frontend`) |
| Landing | `https://scribly.cc` → CT **202** `/var/www/landing` (Caddy vhost) |
| Prod Supabase | CT **201** (`docker exec supabase-db psql -U postgres -d postgres`), env `/root/supabase-project/.env` |
| Dev | CT **206** `dev.scribly.cc`, API :8002, own Supabase, frontend `/opt/scriber-dev/frontend` |
| Workers | CT **203** (redis, rq-worker, Prometheus, ntfy :9095, grafana-ntfy-relay :9096), CT **204/205** GPU (P4) |
| NPM | CT **111**, admin `https://npm.holdheide.com` (no API token available) |
| Grafana | VM **106** `http://192.168.1.106:3000` (use `qm`, not `pct`) |
| SSH helper | `/root/.hermes/neo_ssh.py` (`connect()`, `run(conn, cmd, timeout)`) from LXC 113 |

## Conventions that must be kept

1. **Dev first**: branch → deploy to CT 206 → user looks → merge `main` → prod. Never straight to prod.
2. Deploy pattern: `pct push <ct> /local/file <remote>` then build **on the container**
   (`cd /opt/scriber/frontend && npm run build` for prod, `npx vite build --outDir /var/www/scribly-dev.new`
   on 206, then swap the directory).
3. After a bundle swap the browser caches `index.html` — **hard reload** before judging a UI change.
4. No emoji in UI/copy; landing palette `#0f1115` / `#161a22` / `#2563eb`; inline SVG spark, never `✦`.
5. Quota convention: `-1` unlimited, `0` not available, `n` cap. `app/services/quota.py` is the only
   source of truth for plan limits — every surface (landing pricing, `/pro`, plan line, notification)
   must match it.
6. SQL through `pct exec -- bash -c "... psql ..."` mangles quotes; push a `.sql` file and
   `docker exec -i supabase-db psql -U postgres -d postgres < file`.
7. Cloudflare blocks Python `urllib` (error 1010). Server-side code must call internal addresses
   (`127.0.0.1:9095`, `192.168.1.226:8000`), not the public hostnames.

## Shipped and verified (2026-10-29)

- **Auth**: signups open with email verification, branded Resend templates (recovery, confirmation,
  magic link, invite, email change), set-a-new-password screen, "Forgot password?".
- **Plans**: `public.subscriptions` (free/premium/admin + Stripe-shaped columns), `public.usage_events`
  (append-only log), DB trigger enrols every new account on free. Free = 1/24 h, 500 MB, 15 min, no
  diarization, 7-day shares. Pro = unlimited transcriptions (fair use), 5 GB/24 h, diarization 10/day,
  30-day shares.
- **Enforcement**: 429 allowance, 413 size (aborts mid-stream), 422 length (ffprobe, file deleted),
  402 feature locked. Rejections leave no file/row/job/usage record. `GET /api/me/limits`,
  `POST /api/me/plan` (admin), `GET|POST /api/me/interest`.
- **UI**: plan line under the drop zone; plan-limit notification with "Upgrade to Pro" → `/pro`
  (Pro feature table + request early access); ShareModal day options follow the plan.
- **Marketing**: landing has `#pricing` (Free $0 / Pro $9 per month or $90 a year), CTAs
  "Start free" + "See pricing", FAQ + terms + privacy rewritten to match reality.
- **Alerting**: Grafana → `grafana-ntfy-relay` (203) → ntfy `scriber-alerts` → phone. Rule
  *Node down (scriber-nodes)* proven by stopping a node (FIRING + RESOLVED both delivered).
  ntfy is public at `https://ntfy.scribly.cc` (NPM host 27, cert npm-60).

## Open work, in the order I would do it

1. **Email routing is broken** — `hello@scribly.cc` and `privacy@scribly.cc` are printed on the
   terms/privacy pages but `scribly.cc` has **no MX** and SPF is `v=spf1 -all`, so mail
   to them is refused. Fix = Cloudflare Email Routing (free): enable it, verify a destination inbox,
   add custom addresses, merge SPF to `v=spf1 include:_spf.mx.cloudflare.net -all`. Needs a Cloudflare
   API token (Zone.DNS edit) to do from the shell, or four dashboard clicks by the user.
2. **Restore the 7-day free retention promise (F-9)** — deliberately not built because a naive sweep
   would delete the existing 18-video test library (oldest 28 days, all free-plan). Needs a cutoff
   date, dry-run first, and artifact/media cleanup mirroring `videos_delete.py`.
3. **Hour-based metering** — fair use is policy only; `usage_events` counts transcriptions, not audio
   hours. Add duration to the log and sum it for reporting/throttling.
4. **Rest of the alert rules** — API down, queue depth > 5 for 10 m, worker heartbeat missing, failed
   jobs, disk > 80 %, wedged GPU. Same folder (`scriberly`), same route (`team=scriberly`), same topic.
5. **Stripe (T-1)** — checkout + webhook writing `subscriptions`; `pro_interest` rows are the warm list.
6. Then product depth: transcode (F-6), burn-in render (F-1), subtitle editing (F-2), watermark (F-4),
   bulk upload (F-3/T-8).

## Traps already hit (do not rediscover)

- Stopping a worker CT faster than RQ's worker TTL leaves `rq:worker:scriber-worker-<ct>` in Redis and
  the service crash-loops with `There exists an active worker named …`. `redis-cli del` it on 203.
- ntfy routes are **topic-prefixed**: `POST /<topic>`, `/<topic>/json?poll=1`, `/<topic>/sse`.
  `/v1/json?topic=` returns 400 and `/v1/sse/<topic>` 404 — that is not a proxy fault.
- ntfy 2.28 stores a JSON publish body as message text; publish with `Title:`/`Priority:`/`Tags:`
  headers + plain-text body.
- The app has a global `header { display:flex }` rule — page heroes must not use `<header>`.
- `pct exec` quoting; `sqlite3` is not installed on CT 111 by default; NPM has no docker.

## Credentials — where they are, not what they are

- Supabase keys: `/root/supabase-project/.env` (prod, 201), `/opt/supabase/.env` (dev, 206).
- Grafana admin: see memory / ask the user; ntfy relay creds: `/opt/grafana-ntfy-relay/relay.env` (203).
- ntfy phone account is `scriber`; the relay publishes as `grafana`. Do not paste secrets into the repo.
