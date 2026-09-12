# Scriber

Self-hosted video transcription web app. Upload a video/audio file → faster-whisper ASR on 2× Tesla P4 (Proxmox LXCs) → searchable, editable, exportable transcripts with SRT/VTT/TXT/DOCX exports.

**Status: v0.6.0 — W1–W11 complete. Full web app live with global transcript search, validated on real-world files up to 3h42m (416MB).** Remaining: diarization (W10), sharing (W12), hardening, v1.0.0.

## Features
- **Web app** (http://192.168.1.202): login/signup, drag & drop upload with live progress, video library with real-time job status (Supabase Realtime), one-click delete with confirmation
- **Transcript viewer**: synced playback matched to the transcript (click a segment → seek; playback highlights the active segment), inline segment editing (double-click), search-within-transcript, VTT subtitles, per-video SRT/VTT/TXT/DOCX export + original download
- **Global search**: full-text search across all transcripts (Postgres FTS + GIN index), ranked results with highlighted snippets, click → jumps into the player at that second
- **Robust pipeline**: 10-minute chunked transcription (constant RAM — any file length), GPU-first job routing (CPU fallback), stale-job sweeper (auto-requeue after worker crash/restart), signed media-token URLs, magic-byte content-type sniffing, RFC 5987 unicode filenames
- **JWT-secured API**: Supabase JWKS (ES256) verification; X-User-Id placeholder long gone

## Architecture (5 LXCs on Proxmox host `neo`)

| LXC | IP | Role | Stack |
|-----|----|------|-------|
| supa (201) | 192.168.1.201 | Self-hosted Supabase (Docker) — trimmed 9-container core | Postgres, GoTrue auth, PostgREST, Realtime, Storage, Studio |
| app (202) | 192.168.1.202 | **Caddy :80** (SPA + API) → FastAPI (uvicorn :8001, systemd) + stale-job sweeper timer | FastAPI, supabase-py, RQ client, python-docx, PyJWT |
| worker (203) | 192.168.1.203 | Redis + CPU ASR fallback worker (14 threads) | Redis (AOF), faster-whisper small/int8 |
| gpu1 (204) | 192.168.1.204 | GPU ASR worker → Tesla P4 #0 | faster-whisper **large-v3-turbo/int8**, CTranslate2 |
| gpu2 (205) | 192.168.1.205 | GPU ASR worker → Tesla P4 #1 | same as gpu1 |

**Data flow:** browser → Caddy :80 (SPA + `/api/*` proxy) → FastAPI streams upload in 1MiB chunks → TrueNAS NFS (`192.168.1.116:/mnt/main/transcriber`, bind-mounted at `/mnt/media`) → job row in Postgres → RQ enqueue to `transcribe-gpu` queue → GPU workers pull (CPU worker = fallback) → chunked transcription (10-min segments, no-VAD inside chunks for exact timestamps) → `segments` rows + SRT/VTT/DOCX artifacts on NFS → progress streamed to `jobs` table (Supabase Realtime).

DB stores metadata + transcript text only — media never touches Postgres.

**Benchmarks (Tesla P4, int8):** large-v3-turbo RTF **0.13** (~8× realtime) · small CPU RTF 0.65. Validated real-world: WAN Show 3h42m/416MB (3,882 segments) and 36-min SCANTRON video, both in sync hour+ into playback. Full table in `docs/benchmarks.md`.

## API (behind Caddy, port 80)

```
POST /api/videos/upload          # multipart, JWT bearer
GET  /api/videos                 # list user's videos (+latest job stage/progress)
GET  /api/videos/{id}            # detail
GET  /api/videos/{id}/transcript # full_text + segments (ordered, paged past 1000 rows)
PATCH /api/segments/{id}         # inline segment edit (text/speaker)
GET  /api/videos/{id}/transcript # via transcripts router
GET  /api/videos/{id}/artifacts/srt | vtt | txt | docx
GET  /api/videos/{id}/download   # original file, HTTP Range + signed ?mt= token
GET  /api/videos/{id}/media-token  # 10-min HMAC token for <audio>/<video> src
GET  /api/search?q=              # global FTS, ranked + highlighted
GET  /api/health
```

All endpoints require `Authorization: Bearer <supabase-jwt>` (media streaming also accepts the signed query token).

## Repo layout
```
backend/
  app/
    main.py            FastAPI entrypoint (CORS, routers)
    config.py          env-driven settings
    routers/           videos (upload), videos_list, transcripts, segments, search, health
    services/          auth (JWKS), supabase_client, queue (RQ), media_token, docx_export
    workers/           tasks.py (chunked transcribe_job), worker.py (RQ entrypoint)
    worker_config.py   worker-side env (device/model/compute per LXC)
  deploy/              systemd units (api, rq-worker@, requeue timer), Caddyfile
  scripts/             requeue_stale.py (watchdog)
  tests/               pytest (7: health, auth, validation)
  .env.example         template (never commit real keys)
frontend/              Vite + React + TS: auth, upload, video list, viewer/editor, search
migrations/            0001_init.sql (schema+RLS+realtime), 0002_fts.sql (search)
scripts/
  scriber-status.sh    one-shot fleet status (run on neo)
docs/                  architecture, runbook, benchmarks
```

## Ops quick reference
- **Status:** `bash /root/scriber-status.sh` on neo
- **Deploy backend:** tar `backend/` → `pct push 202` → extract `/opt/scriber` → `systemctl restart transcriber-api`
- **Deploy workers:** same to 203/204/205 + `systemctl restart rq-worker@<id>`
- **Deploy frontend:** tar `frontend/` → build on 202 with `VITE_SUPABASE_*` env → Caddy serves `dist/`
- **Stale-job sweeper:** `scriber-requeue.timer` on 202 (requeues jobs with no heartbeat for 3 min)
- **Docs:** `docs/architecture.md` · `docs/runbook.md` · `docs/benchmarks.md`

## Roadmap
- [x] W1: Infra — 5 LXCs, GPU passthrough (550 driver, kernel pinned 6.14), NFS via host bind-mount
- [x] W2: Supabase — trimmed stack, secrets, buckets, email autoconfirm
- [x] W3: Schema + RLS (owner-only) + Realtime on jobs
- [x] W4: FastAPI + streaming upload (M1)
- [x] W5/6: GPU compute validated + RQ pipeline, parallel/kill-recovery soaks
- [x] W7: Caddy :80, artifact endpoints, DOCX export, 500MB upload proof (v0.3.0)
- [x] W8: Frontend + JWT auth — login, drag&drop, Realtime status (v0.4.0)
- [x] W9: Viewer/editor — synced playback, inline edit, search-in-transcript (v0.5.0)
- [x] Long-file hardening: chunked transcription (OOM), VAD drift fix, 1000-row paging, unicode filenames, stale-job sweeper, GPU-first routing
- [x] W11: Global FTS search with click-to-jump (v0.6.0)
- [ ] W10: Diarization (pyannote on P4) — next
- [ ] W12: Share links, batch upload, notifications · W13: hardening/backups
- [ ] W14/W15: largely pre-validated by real-file testing · W16: TLS + v1.0.0
