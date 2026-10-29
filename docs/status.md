# Scribly status — verified live 2026-10-27 22:40 UTC (rewritten)

All facts below were checked live this pass: `pct` on host **neo** (192.168.1.109) via SSH,
psql inside `supabase-db` on 201, HTTP probes on 202, and public URL probes from LXC 113.

## Deployment — up

| LXC | Name | Services verified active |
|---|---|---|
| 201 | vm201-supa | 9 containers: `supabase-auth, storage, realtime, meta, rest, envoy, db, studio, imgproxy` |
| 202 | vm202-app | `transcriber-api` (:8001, `/docs` 200, `/api/health` 200), `caddy` (:80 200), `app-exporter` |
| 203 | vm203-worker | `redis-server`, `rq-worker@203`, `prometheus` (:9090 healthy), `ntfy` |
| 204 | vm204-gpu1 | `rq-worker@204`, `gpu-exporter` (Tesla P4, idle 0 MiB) |
| 205 | vm205-gpu2 | `rq-worker@205`, `gpu-exporter` (Tesla P4, idle 0 MiB) |

Queues: `transcribe-gpu=0, transcribe=0, diarize=0, default=0`. Host uptime 6d 10h.

GPU worker env (both 204 **and** 205 now verified identical): `torch 2.5.1+cu121`,
`torch.cuda.is_available()=True`, `ctranslate2 CUDA devices=1`, `numpy 1.26.4`,
`huggingface_hub 0.36.2`, `matplotlib 3.7.5`. F-12 global re-clustering
(`AgglomerativeClustering … distance_threshold=0.715`) is present in `diarize_tasks.py` on both.

## Media storage — local ZFS dataset (migrated 2026-10-27, NFS retired)

Media no longer lives on TrueNAS. It is now a **single ZFS dataset on neo**, bind-mounted into
every consumer, so there is no network filesystem in the hot path:

```
zpool  neoDATA  (RAIDZ1, 5.45T total / 4.69T free)
 └─ neoDATA/media   /neoDATA/media   5.39G used   atime=off, compression=zstd
     ├─ videos/      3.9G  94 files (originals + srt/vtt/docx/pdf/thumb)
     ├─ hf-cache/    1.6G  whisper + pyannote models (HF_HOME=/mnt/media/hf-cache)
     ├─ pg/          nightly pg_dump of Supabase (dev bench/journal)
     ├─ backups/     grafana dashboards
     └─ .nvidia-libs-550/  (27M, legacy fallback, unused)
```

Mounted as `mp0: /neoDATA/media,mp=/mnt/media` in **201, 202, 203, 204, 205** — path unchanged,
so no code or env edits were needed. Files inside the CTs are owned by `root` (host uid `100000`),
which fixes the old NFS-squash weirdness where everything appeared as `nobody`/65534.

**One dataset on purpose:** a bind mount does not cross filesystem boundaries, so child datasets
(`neoDATA/media/videos`, `…/hf-cache`) appeared as EMPTY directories inside the CTs. They were
folded into the parent dataset so `mp0` exposes everything and `zfs snapshot neoDATA/media` covers
all of it in one shot.

Verified after cutover: 94/94 files visible in 202, write test OK, `api/health` 200, frontend 200,
both P4s `cuda=True` / `ctranslate2=1`, all queues empty, rq workers active, and a real media read
`GET /api/videos/<id>/download` → **206 Partial Content** (`content-range: bytes 0-1023/790764862`),
thumbnail 200, srt 200.

### Pipeline smoke test on the new storage (2026-10-27)

A 3-minute slice cut from DLSS 5 was uploaded as a **new** video through the API and processed
end-to-end: queued → done in ~40 s, 93 segments, `last_end_ms=179700` (matches the 180 s clip),
artifacts `srt/docx/pdf` all 200 with real bytes, thumbnail 200, then `DELETE` 200. The test video
was removed afterwards; library is back to 18 videos / 13,685 segments / 94 media files.

**Bug found by that test and fixed:** `videos_delete.py` only removed `.srt/.vtt/.docx/.txt/.thumb.jpg`
— the **PDF was never deleted**, and the dual-mode `-generic.*` exports weren't either, so every
delete leaked files (a real problem once F-9 auto-delete starts). `ARTIFACT_EXTS` now includes
`.pdf` and the handler globs `<uuid>-generic*`. Deployed to 202, API restarted, re-tested: delete now
leaves zero files. Pre-fix orphan cleaned up manually.

### Scheduled protection (installed 2026-10-27)

| Unit / cron | Where | What |
|---|---|---|
| `scribly-media-snapshot.timer` | neo, daily 03:15 | `zfs snapshot neoDATA/media@auto-<ts>`, keeps newest 14 (hard cap 18) |
| `scribly-media-offsite.timer` | neo, Sun 05:00 | mounts TrueNAS read/write, `rsync -a --delete` videos+hf-cache+backups, unmounts, skips when NAS is unreachable |
| `scribly-pgdump.sh` (cron 03:30) | 201 | `pg_dump` → `/mnt/media/pg/scribly-<date>.sql.gz`, keep 7 days |

TrueNAS is now **cold backup only**: its fstab line is commented out and the automount is disabled,
so the box being off cannot hang the app. Rollback if ever needed: uncomment the fstab line,
`systemctl enable --now 'mnt-transcriber\x2dnfs.automount'`, point `mp0` back.

## Data (live DB)

| Table | Rows |
|---|---|
| videos | 18 (all `done`) |
| transcripts | 18 |
| segments | 13,685 |
| jobs | 35 |
| share_links | 8 |
| auth.users | 3 — `test@scriber.local`, `austin.holdheide@outlook.com`, `english@scribly.local` |

Diarized: WAN Show 3h42m → 2 speakers (`speaker_order` = Speaker 1/2, 75.3% / 21.3%);
DLSS 5 → 1 speaker. The FBI-episode video still holds **19 speaker labels in segments with no
`speaker_order`** — leftover from the pre-fix over-segmentation run; it needs a re-diarize (or
label cleanup) before it's usable. Last job activity: 2026-10-25 19:44 UTC.

## Public surface

- `https://app.scribly.cc` → **no DNS yet** (record + cert pending); NPM host 20 already forwards both `app.scribly.cc` and `pocscribly.holdheide.com` → 202:80
- `https://pocscribly.holdheide.com` → 200 (legacy app name, being retired once `app` resolves)
- `https://db.scribly.cc/auth/v1/health` → 401 without apikey (correct: proxy reaches Supabase envoy)
- `https://app.scribly.cc` → no DNS/host (000); `https://scribly.cc` → 404 — launch wiring not done
- Frontend bundle on 202: `index-0MLZu-PO.js` (built 2026-10-02), `.env.local`
  `VITE_SUPABASE_URL=https://db.scribly.cc`

## Backups

Nightly vzdump 04:00 → `neoDATA`, `keep-last=3`, snapshot mode, vmids 201,202,203,204,205.
**Not covered:** media files (TrueNAS dataset — needs TrueNAS-side snapshots) and a logical
`pg_dump` of the Supabase DB (W13 leftover).

## Closed since the previous status doc (was stale)

- ~~Diarization stalls on long files~~ → chunked diarization (`a00a427`) + 24 h RQ timeout.
- ~~205 not mirrored~~ → 205 verified with the identical pin set.
- ~~Cross-chunk speaker continuity naive~~ → F-12 global re-clustering (commits `5190d2d`, `57b4cd9`),
  verified on WAN Show + DLSS 5.

## Open

1. **TrueNAS offline** (above) — blocks everything media-related.
2. **GitHub push lag** — remote `main` = `ab814f3` (2026-10-08). Local Windows repo has
   `57b4cd9` (fold fix) + `ec167d4` (roadmap) committed but never pushed (VPN upload stall).
3. **E-1 / W16-3** — POC still shares the production Supabase on 201; split environments before
   exposing `app.scribly.cc` to real users.
4. **Launch path:** W16-1/2 (DNS + LE cert for `app.scribly.cc`), F-5 (SMTP/Resend + GoTrue
   verification), then F-6 transcode pipeline (biggest build), then tiers T-1…T-8.
5. **FBI video speaker cleanup** (19 labels, no `speaker_order`).
6. W13 leftovers: `pg_dump` cron to TrueNAS, Grafana provisioning-as-code, uptime alerting.
7. Ops: 204 rootfs 20 G (43% used), 205 20 G (68% used) — O-2 bump to 32 G is still worth doing.

Testing convention unchanged: validate pipeline changes on a **short real file** (36-min DLSS 5
clip) before a multi-hour run.

## Environments (E-1, first phase built 2026-10-28)

| | prod | dev |
|---|---|---|
| Host / CT | neo **201–205** | neo **LXC 206** `vm206-scribly-dev` @ **192.168.1.226** |
| Supabase | 201, 9 containers | 206, 9 containers (own keys, own DB) |
| API | 202 `transcriber-api` :8001 | 206 `transcriber-api-dev` :8002 |
| Redis / queues | 203 | 206, local `127.0.0.1` |
| Workers | `rq-worker@203/204/205` (P4s) | `rq-worker-dev` (CPU, always on) + `rq-worker-dev-gpu` (**disabled**, opt-in P4) |
| Media | `neoDATA/media` → `/mnt/media` | `neoDATA/dev/media` → `/mnt/media` |
| DB data | docker volume | `neoDATA/dev/pgdata` (dataset, snapshot-able) |
| Frontend | Caddy :80 on 202 | nginx :80 on 206 (`/api/` → 127.0.0.1:8002), bundle built with dev URL only |
| Public URL | `pocscribly.holdheide.com` (until W16) | LAN only, no DNS yet |

**IP note:** dev was first built on .206 — that address belongs to the **iDRAC**; it now lives on **.226**. Anything (env file, baked bundle, doc) referencing .206 for Scribly is stale.

**Isolation verified:** 18 secret keys compared dev vs prod → `SHARED_WITH_PROD: none` (JWT_SECRET, anon/service, ES256 `JWT_KEYS`/`JWKKS`, Postgres password, vault/pg-meta/realtime keys). Dev tokens cannot authenticate against prod. Schema+data seeded by restoring the nightly `pg_dump` (18 videos / 13,685 segments), and 60 s upload→transcribe→artifacts→delete ran clean on dev.

**Dev-only pins that matter:** `av==18.1.0` (Python 3.13 otherwise pulls av 19, whose PyAV dropped the `metadata_errors` kwarg faster-whisper passes → every job dies while reporting "completed"); RQ worker listens on `transcribe-gpu` (`RQ_QUEUE`) because the API always enqueues there.

**Not done yet:** DNS/TLS for `dev.scribly.cc` + `dev-db.scribly.cc`, Prometheus job for dev, dev-first migration rule + `deploy.sh <env>` guard, prod account clean-up for launch.

## Landing page (W16-5, built 2026-10-28)

Static, single-file, no build step, no external requests — `landing/` in the repo
(`index.html`, `privacy.html`, `terms.html`). Same palette as the app (`#0f1115` / `#161a22` / `#2563eb`),
emoji-free (SVG spark instead of the ✦ glyph so it renders everywhere), responsive down to phone width.

Deployed to **202** at `/var/www/landing` and served by a new Caddy vhost matching
`http://scribly.cc, http://www.scribly.cc` (TLS terminates at NPM; Caddy only speaks HTTP:80).
The existing `:80` catch-all still serves the app, so app hosts are unaffected — verified after reload:
`Host: scribly.cc` → landing, `Host: pocscribly.holdheide.com` → app bundle, `/api/health` → 200.

**Still needed:** NPM proxy host for `scribly.cc` + `www.scribly.cc` → `192.168.1.202:80` (Cloudflare DNS
already resolves the apex). The CTA currently points at the demo instance `pocscribly.holdheide.com`;
switch to `app.scribly.cc` at launch. Privacy/Terms are honest drafts, not reviewed policy.

## GitHub repo (2026-10-28)

Five commits are prepared on top of `ab814f3` in `/root/git/Scriber` and **not yet pushed** (this host has
no GitHub credential):

| Commit | Content |
|---|---|
| `78eb200` | F-12 fold fix (captured from the deployed GPU workers — same content as the unpushed Windows commit `57b4cd9`) |
| `af23555` | delete now removes `.pdf` + `-generic.*` artifacts |
| `ac7b784` | `landing/` (scribly.cc site) |
| `47b935c` | `ops/` (zfs snapshot, offsite rsync, pg_dump) |
| `45590e9` | docs: `environments.md`, architecture storage section, runbook failure modes, README refresh |

Push with `/root/push_scribly.sh` after placing a PAT in `/root/.github-token`. The Windows checkout is
2 commits ahead of origin (`57b4cd9`, `ec167d4`); once this is pushed, back those up
(`git branch backup-local-main`), then `git fetch origin && git reset --hard origin/main` — the fold fix
and roadmap edits are already contained in these commits.

## Launch blockers closed

- **Open signup on prod** — closed 2026-10-28: `DISABLE_SIGNUP=true` on 201, verified `422 signup_disabled`
  from the public API while password login still returns 200. Accounts are now admin-created
  (`auth/v1/admin/users`). Both bundles hide the signup affordance (`VITE_SIGNUP_ENABLED=false`).

## Launch blockers closed

- **Open signup on prod** — closed then re-opened *with verification* (2026-10-29): branded confirmation
  email via Resend, unconfirmed accounts get `400 Email not confirmed`, 30s per-address send throttle.
- **Password reset** — branded recovery email plus a "Choose a new password" screen in the app (was: the
  link logged you in with no way to set a password).
- **Transactional email** — Resend SMTP on both stacks (`smtp.resend.com:587`), templates served from
  202 at `/email/*.html`, subjects per type.

