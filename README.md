# Scribly

**Scribly** (formerly Scriber) — self-hosted video transcription web app. Live at **https://scribly.cc** (LAN: http://192.168.1.202). Upload a video/audio file → faster-whisper ASR on 2× Tesla P4 (Proxmox LXCs) → searchable, editable, exportable, shareable transcripts.

**Status: v0.7.0 — W1–W12 complete.** Full web app live with global hybrid search, expiring share links, PDF export, push notifications, and thumbnails — validated on real-world files up to 3h42m (416MB). Remaining: diarization (W10), hardening (W13), v1.0.0.

## Features

### Core
- **Web app** (http://192.168.1.202): login/signup, drag & drop upload with live progress, thumbnail library, real-time job status (Supabase Realtime)
- **Transcript viewer**: synced playback matched to the transcript (click a segment → seek; playback highlights the active segment), inline segment editing (double-click), search-within-transcript, compact PDF + SRT/DOCX exports + original download via ☰ menu
- **Re-transcribe / cancel**: re-run any video through the current pipeline without re-uploading; cancel running or queued jobs (worker heartbeats honor the cancel flag)
- **Global search**: hybrid matching — full-text FTS + word-prefix + substring — so `search` finds *research*/*unsearchable* and `transcri` finds *transcription*; ranked results with highlighted snippets, click → jumps into the player
- **Robust pipeline**: 10-minute chunked transcription (constant RAM — any file length), GPU-first job routing (CPU fallback), stale-job sweeper + cancel convergence, signed media-token URLs, magic-byte content-type sniffing, RFC 5987 unicode filenames
- **JWT-secured API**: Supabase JWKS (ES256) verification on every endpoint

### Sharing (W12)
- **Expiring share links** (1–30 days, revocable): read-only transcript page that mirrors the viewer — same two-column layout, synced playback, click-to-seek, search — no account needed
- Shares include media playback (token-authorized streaming with HTTP Range seeking) and downloads (SRT/DOCX/PDF/original)

### Extras
- **PDF export**: compact timestamped segment layout (fpdf2 + DejaVu, unicode-safe), all segments (paged past PostgREST caps)
- **Push notifications**: self-hosted ntfy — phone push when a job finishes, fails, or is cancelled
- **Thumbnails**: ffmpeg 320px frame grab at upload/transcription; library list + video poster
- **Clipboard that works on plain-HTTP LAN**: execCommand fallback (navigator.clipboard is HTTPS-only)

## Architecture (5 LXCs on Proxmox host `neo`)

| LXC | IP | Role | Stack |
|-----|----|------|-------|
| supa (201) | 192.168.1.201 | Self-hosted Supabase (Docker) — trimmed 9-container core | Postgres, GoTrue auth, PostgREST, Realtime, Storage, Studio |
| app (202) | 192.168.1.202 | **Caddy :80** (SPA + API) → FastAPI (uvicorn :8001, systemd) + stale-job sweeper timer | FastAPI, supabase-py, RQ client, fpdf2, PyJWT |
| worker (203) | 192.168.1.203 | Redis + CPU ASR fallback worker (14 threads) + **ntfy server (:9095)** | Redis (AOF), faster-whisper small/int8, ntfy v2.28 |
| gpu1 (204) | 192.168.1.204 | GPU ASR worker → Tesla P4 #0 | faster-whisper **large-v3-turbo/int8**, CTranslate2 |
| gpu2 (205) | 192.168.1.205 | GPU ASR worker → Tesla P4 #1 | same as gpu1 |

**Data flow:** browser → Caddy :80 (SPA + `/api/*` proxy) → FastAPI streams upload in 1MiB chunks → TrueNAS NFS (`192.168.1.116:/mnt/main/transcriber`, host automount → bind-mounted at `/mnt/media`) → job row in Postgres → RQ enqueue (`scriber-<job_id>`, deterministic) → GPU workers pull (CPU worker = fallback) → chunked transcription (10-min segments, no-VAD inside chunks for exact timestamps) → thumbnail grab → `segments` rows + SRT/DOCX/PDF artifacts on NFS → progress streamed to `jobs` table (Supabase Realtime) → ntfy push on done/failed.

DB stores metadata + transcript text only — media never touches Postgres.

**Benchmarks (Tesla P4, int8):** large-v3-turbo RTF **0.13** (~8× realtime) · small CPU RTF 0.65. Validated real-world: WAN Show 3h42m/416MB (3,882 segments) and 36-min SCANTRON video, both in sync hour+ into playback. Full table in `docs/benchmarks.md`.

## API (behind Caddy, port 80)

```
POST /api/videos/upload               # multipart, JWT bearer; grabs thumbnail async
GET  /api/videos                      # list (+stage/progress/has_thumb)
GET  /api/videos/{id}                 # detail (+has_thumb, human error)
POST /api/videos/{id}/retranscribe    # re-run pipeline, replaces transcript
POST /api/videos/{id}/cancel          # cancel active job (queued or running)
DELETE /api/videos/{id}               # delete video + artifacts
GET  /api/videos/{id}/transcript      # full_text + segments (paged past 1000 rows)
PATCH /api/segments/{id}              # inline segment edit (text/speaker)
GET  /api/videos/{id}/artifacts/srt | docx | pdf
GET  /api/videos/{id}/download        # original file, HTTP Range + signed ?mt= token
GET  /api/videos/{id}/media-token     # 10-min HMAC token for <audio>/<video> src
GET  /api/videos/{id}/thumbnail       # JPEG frame (Bearer or signed ?mt=&mu=)
POST /api/videos/thumb-tokens         # batch tokens for the library view
POST /api/videos/{id}/shares          # create share link {days: 1..30}
GET  /api/videos/{id}/shares          # list my links (expired/revoked flagged)
DELETE /api/videos/shares/{id}        # revoke a link
GET  /api/videos/public/{token}       # PUBLIC: transcript payload
GET  /api/videos/public/{token}/media     # PUBLIC: media stream (Range supported)
GET  /api/videos/public/{token}/thumb     # PUBLIC: poster frame
GET  /api/videos/public/{token}/artifact/{srt|docx|pdf|txt}  # PUBLIC: downloads
GET  /api/search?q=                   # global hybrid search, ranked + highlighted
GET  /api/health
```

All non-public endpoints require `Authorization: Bearer *** (media streaming also accepts the signed query token).

## Repo layout
```
backend/
  app/
    main.py            FastAPI entrypoint (CORS, routers)
    config.py          env-driven settings
    routers/           videos (upload), videos_list, videos_ops, videos_thumb,
                       shares, transcripts, segments, search, health
    services/          auth (JWKS), supabase_client, queue (RQ), media_token,
                       thumbs, pdf_export, notify (ntfy), docx_export
    workers/           tasks.py (chunked transcribe_job + cancel + thumb + notify),
                       worker.py (RQ entrypoint)
    worker_config.py   worker-side env (device/model/compute per LXC)
  scripts/             requeue_stale.py (watchdog), backfill_thumbs.py
  tests/               pytest
  .env.example         template (never commit real keys)
frontend/              Vite + React + TS: auth, library w/ thumbs, viewer/editor,
                       share modal, public share page, search
migrations/            0001 init · 0002 fts · 0003 cancel+thumbs · 0004 share_links
                       · 0005 search hybrid
observability/         Grafana dashboards, ntfy server config example
docs/                  architecture, runbook, benchmarks
```

## Ops quick reference
- **Status:** `bash /root/scriber-status.sh` on neo
- **Deploy backend:** tar `backend/` → `pct push 202` → extract `/opt/scriber` → `systemctl restart transcriber-api`
- **Deploy workers:** same to 203/204/205 + `systemctl restart rq-worker@<id>`
- **Deploy frontend:** `frontend/.env.local` must hold `VITE_SUPABASE_*` → `npm run build` on 202 → Caddy serves `dist/`
- **After a host reboot:** run `nvidia-smi` once on the host (creates uvm node), then `pct restart 204 205` — service restarts do NOT rebind GPU devices
- **ntfy:** subscribe your phone to `scriber-<first 10 chars of user id>` at `http://192.168.1.203:9095` (user: scriber)
- **Docs:** `docs/architecture.md` · `docs/runbook.md` · `docs/benchmarks.md`

## Roadmap
- [x] W1–W6: Infra, Supabase, schema/RLS, upload, GPU pipeline, soaks
- [x] W7–W9: Caddy + artifacts, frontend + auth, viewer/editor (v0.3–v0.5)
- [x] W10-lite hardening: chunked transcription, VAD policy, paging, unicode, sweeper, GPU routing
- [x] W11: Global FTS search with click-to-jump (v0.6.0)
- [x] W16-lite cheap wins: re-transcribe, cancel, thumbnails (v0.6.x)
- [x] W12: Share links + public viewer, PDF export, ntfy notifications, hybrid search (v0.7.0)
- [ ] W10: Diarization (pyannote on P4) — next
- [ ] W13: pg_dump drill, Grafana provisioning-as-code, uptime alerting
- [ ] W14/W15: Playwright E2E, security audit · W16: TLS + domain + v1.0.0
