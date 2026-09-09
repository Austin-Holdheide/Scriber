# Scriber

Self-hosted video transcription web app. Upload a video/audio file → faster-whisper ASR on 2× Tesla P4 (Proxmox LXCs) → searchable, editable, exportable transcripts with SRT/VTT/TXT/DOCX exports.

**Status: v0.3.0 — W1–W7 complete. Full pipeline live: upload → GPU transcription → segments → exports.** Frontend (W8) is next.

## Architecture (5 LXCs on Proxmox host `neo`)

| LXC | IP | Role | Stack |
|-----|----|------|-------|
| supa (201) | 192.168.1.201 | Self-hosted Supabase (Docker) — trimmed 9-container core | Postgres, GoTrue auth, PostgREST, Realtime, Storage, Studio |
| app (202) | 192.168.1.202 | **Caddy :80** → FastAPI (uvicorn :8001, systemd) | FastAPI, supabase-py, RQ client, python-docx |
| worker (203) | 192.168.1.203 | Redis + CPU ASR fallback worker (14 threads) | Redis (AOF), faster-whisper small/int8 |
| gpu1 (204) | 192.168.1.204 | GPU ASR worker → Tesla P4 #0 | faster-whisper **large-v3-turbo/int8**, CTranslate2 |
| gpu2 (205) | 192.168.1.205 | GPU ASR worker → Tesla P4 #1 | same as gpu1 |

**Data flow:** browser → Caddy :80 → FastAPI streams upload in 1MiB chunks → TrueNAS NFS (`192.168.1.116:/mnt/main/transcriber`, bind-mounted at `/mnt/media`) → job row in Postgres → RQ enqueue via Redis (203) → GPU workers pull → ffmpeg extract 16k mono → int8 transcribe → `segments` rows + SRT/VTT/DOCX artifacts written back to NFS → progress streamed to `jobs` table (Supabase Realtime).

DB stores metadata + transcript text only — media never touches Postgres.

**Benchmarks (Tesla P4, int8):** large-v3-turbo RTF **0.13** (~8× realtime) · small CPU RTF 0.65. Full table in `docs/benchmarks.md`.

## API (behind Caddy, port 80)

```
POST /api/videos/upload          # multipart, X-User-Id until JWT lands (W8)
GET  /api/videos                 # list user's videos
GET  /api/videos/{id}            # detail
GET  /api/videos/{id}/transcript # full_text + segments (ordered)
GET  /api/videos/{id}/artifacts/srt | vtt | txt | docx
GET  /api/videos/{id}/download   # original file (streamed from NFS)
GET  /api/health
```

## Repo layout
```
backend/
  app/
    main.py            FastAPI entrypoint (CORS, routers)
    config.py          env-driven settings
    routers/           videos (upload/list), videos_list, transcripts, health
    services/          supabase_client (service key), queue (RQ), docx_export, upload
    workers/           tasks.py (transcribe_job), worker.py (RQ entrypoint)
    worker_config.py   worker-side env (device/model/compute per LXC)
  deploy/              systemd units, Caddyfile
  tests/               pytest (health, auth-required, ext-validation)
  .env.example         template (never commit real keys)
frontend/              Vite + React + TS (W8)
migrations/            SQL applied to Supabase Postgres (schema v1: videos/transcripts/segments/jobs + RLS)
scripts/
  scriber-status.sh    one-shot fleet status (run on neo)
docs/                  architecture, runbook, benchmarks
```

## Ops quick reference
- **Status:** `bash /root/scriber-status.sh` on neo
- **Deploy backend:** tar `backend/` → `pct push 202` → extract `/opt/scriber` → `systemctl restart transcriber-api`
- **Deploy workers:** same to 203/204/205 + `systemctl restart rq-worker@<id>`
- **Docs:** `docs/architecture.md` · `docs/runbook.md` · `docs/benchmarks.md`

## Roadmap
- [x] W1: Infra — 5 LXCs, GPU passthrough (550 driver, kernel pinned 6.14), NFS via host bind-mount
- [x] W2: Supabase — trimmed stack, secrets, buckets (uploads 5GB / transcripts 100MB), email autoconfirm
- [x] W3: Schema + RLS (owner-only on all 4 tables) + Realtime on jobs
- [x] W4: FastAPI + streaming upload (M1)
- [x] W5/6: GPU compute validated + RQ pipeline, parallel/kill-recovery soaks
- [x] W7: Caddy :80, transcript/artifact endpoints, DOCX export, 500MB upload proof (v0.3.0)
- [ ] W8: Frontend — auth, drag&drop upload, Realtime job status, JWT middleware
- [ ] W9: Viewer/editor (synced playback, inline edit)
- [ ] W10: Diarization (pyannote on P4)
- [ ] W11: Search (FTS) · W12: sharing/notifications · W13: hardening · W14: scale soaks
- [ ] W15: security/E2E pass · W16: TLS + v1.0.0
