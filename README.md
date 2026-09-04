# Scriber

Self-hosted video transcription web app. Upload a video → Whisper ASR (GPU Tesla P4 x2 on Proxmox) → searchable, editable, exportable transcripts.

## Architecture (3 tiers on Proxmox host `neo`)
| LXC | IP | Role |
|-----|----|----|
| supa (201) | 192.168.1.201 | Self-hosted Supabase (Docker Compose): Postgres, Auth, REST, Realtime, Storage |
| app (202) | 192.168.1.202 | FastAPI backend + Caddy serving React frontend |
| worker (203) | 192.168.1.203 | Redis + RQ — CPU ASR fallback (14 cores, faster-whisper int8) |
| gpu1 (204) | 192.168.1.204 | GPU ASR worker → Tesla P4 #0 (faster-whisper int8, CUDA) |
| gpu2 (205) | 192.168.1.205 | GPU ASR worker → Tesla P4 #1 |

Media files: TrueNAS NFS share `192.168.1.116:/mnt/main/transcriber` (bind-mounted to `/mnt/media` in 202-205).
DB stores metadata + transcript text only; video/audio never enters Postgres.

## Repo layout
```
backend/          FastAPI app (runs in app LXC)
  app/            routers / services / workers packages
  tests/          pytest
frontend/         Vite + React + TypeScript (runs via Caddy in app LXC)
migrations/       plain SQL applied to Supabase Postgres
docs/             architecture, runbook, benchmarks
```

## Docs
- `docs/architecture.md` — components, network map, data flow
- `docs/runbook.md` — restart order, backups, common failures
- `docs/benchmarks.md` — ASR model benchmarks (W5)

## Status
- [x] W1: LXCs provisioned, GPU passthrough, NFS storage, Docker + Supabase on 201
- [ ] W2: Supabase configured (secrets, buckets, trimmed stack)
- [ ] W3: Schema + RLS
- [ ] W4: FastAPI skeleton + streaming upload (M1)
