# Changelog

Releases before v0.8.0 exist as git tags only. Dates are the tag date.

## v0.8.0 — 2026-11-02

The release where Scribly became a product rather than a personal tool: a public name and domain,
accounts with plans and enforced quotas, a marketing site, phone alerting, and uploads that work
through a CDN.

### Rebrand and public surface

- Scriber → **Scribly**, served at `scribly.cc` (landing) and `app.scribly.cc` (app) behind Cloudflare
  and Nginx Proxy Manager; Supabase gateway exposed separately at `db.scribly.cc` (API prefixes only,
  studio/dashboard blocked).
- Static marketing site in `landing/` — hero, features, how it works, pricing, FAQ, plus `terms.html`
  and `privacy.html` rewritten to match what the code actually does.
- Pricing published as Free $0 / Pro $9 per month or $90 a year, with the sale state beside it
  ("coming soon — nothing is charged today"). Every number comes from `backend/app/services/quota.py`.

### Accounts and plans (F-7, T-3)

- Email-verified signups with branded Resend templates (confirmation, recovery, magic link, invite,
  email change), a set-a-new-password screen and "Forgot password?".
- `public.subscriptions` (free / premium / admin, Stripe-shaped columns) and append-only
  `public.usage_events`; a DB trigger enrols every new account on the free plan, so signups through the
  app, the admin API or a future invite flow are all covered.
- Enforcement in the order the work happens: **429** rolling allowance before a byte is read, **413**
  when the byte cap is crossed mid-stream, **422** when the duration cap fails after the file lands,
  **402** for a locked feature. A refused upload leaves no file, row, job or usage event.
- `GET /api/me/limits`, `POST /api/me/plan` (admin), `GET|POST /api/me/interest`.
- Plan-limit notification with an "Upgrade to Pro" CTA and a real `/pro` page; free accounts see the
  prompt, premium/admin never do. Pro is worded "unlimited" and the code agrees
  (`QUOTA_PREMIUM_UPLOADS=-1`); fair use is the ceiling, per-file caps (5 GB / 24 h) bound cost.

### Uploads

- **Chunked uploads** — `POST /api/videos/upload/init`, `PUT .../part/{n}`, `GET .../{id}`,
  `POST .../complete`, `DELETE .../{id}` — because Cloudflare refuses a single request body over 100 MB
  on Free/Pro, which made the 500 MB free cap and the 5 GB Pro cap unreachable through the public
  hostname. Parts are 64 MiB, appended in order to one file so the final move is a rename, and resume is
  server-driven (`next_index = received // part_size`).
- The single-shot `POST /api/videos/upload` stays for small clients; both paths finish in
  `services/ingest.py` so the length gate, rows, enqueue and usage event cannot drift apart.

### Diarization (W10, F-12)

- pyannote speaker-diarization-3.1 on the Tesla P4s, 10-minute chunks so multi-hour files never hang in
  one pipeline call, turns re-offset to global time.
- Global speaker re-clustering across all chunks (wespeaker embeddings, agglomerative clustering on
  cosine distance), duration-weighted majority vote to reconcile chunk-local labels, micro-clusters
  under 5% of speech folded into their nearest large cluster.
- Generic "Speaker 1/2/3" toggle and dual-mode downloads (`?spk=real|generic`).

### Storage and operations

- Media moved off NFS onto a local ZFS dataset `neoDATA/media`, bind-mounted into every app container:
  daily `zfs snapshot` (keep 14), nightly `pg_dump` to `/mnt/media/pg`, weekly `rsync` to the NAS as a
  cold copy. TrueNAS is now backup-only, so it being off cannot hang the app.
- A second environment on its own container with its own Supabase, Redis, keys and media, plus
  `dev-db.scribly.cc`; deploys go dev first, then prod.
- **Phone alerting**: Prometheus → Grafana → webhook → relay → ntfy. Rules cover node down, API down,
  worker not running, worker restart loop, queue backlog, new failed jobs, disk over 80%, GPU wedged,
  GPU temperature and metrics-exporter down. Proven by stopping a metrics-only service and watching
  FIRING and RESOLVED both arrive.

### Fixes

- Deleting a video now removes the PDF and the dual-mode `-generic` artifacts (every delete used to
  leak files).
- Artifacts endpoint returned 422 — a stray route decorator shadowed the handler.
- Library list no longer comes back empty after navigating away and back.
- Long-file diarization no longer hangs or times out.
- Emoji removed from the UI (the `✦` glyph rendered as tofu in some clients) in favour of inline SVG.
- Header/page spacing fixes; app favicon matches the landing page.

### Known limits at this tag

- **Nothing auto-deletes on any plan.** The 7-day retention on free is policy, not code — F-9 is open,
  and a naive sweep would delete the operator's existing free-plan library.
- **Fair use is policy only.** `usage_events` counts transcriptions, not audio hours.
- **No checkout.** Pro is granted by an admin call to `POST /api/me/plan`; Stripe (T-1) is not built.
- Worker health is unit-level, not RQ-level: a live unit holding a stale `rq:worker:` key is only caught
  while systemd retries.
