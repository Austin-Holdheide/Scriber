# Scriber — Architecture

## Components
```
[Browser / curl]
   │  HTTP (LAN, TLS in W16)
   ▼
[Caddy :80 — LXC 202 "app"]  (5GB body cap)
   ├── /            → static React build (frontend/dist)
   └── /api/*       → uvicorn FastAPI (127.0.0.1:8000, 2 workers)
                         │
                         ├── supabase-py (service key) ──► [Supabase — LXC 201 :8000 via Kong]
                         │                                    ├─ Postgres (videos/transcripts/segments/jobs)
                         │                                    ├─ Auth (GoTrue), REST (PostgREST), Realtime, Storage
                         └── RQ enqueue ──► [Redis :6379 — LXC 203 "worker"]
                                                │
                                 ┌──────────────┴──────────────┐
                                 ▼                             ▼
                          [RQ CPU worker 203]         [RQ GPU workers 204/205]
                          faster-whisper int8          faster-whisper int8 CUDA
                          14 threads                   P4 #0 / P4 #1
                                 └──────────────┬──────────────┘
                                                ▼
                              ffmpeg → 16k mono wav → ASR → segments
                                                │
                                                ▼
                    TrueNAS NFS 192.168.1.116:/mnt/main/transcriber
                    (host-mounted /mnt/transcriber-nfs, bind-mounted as /mnt/media in 202-205)
```

## Data flow
1. Upload: browser → Caddy /api/upload → FastAPI streams to /mnt/media/videos/{user_id}/{uuid}.{ext} → insert `videos` row (status=uploaded) → enqueue RQ job → status=queued.
2. Worker picks up: update jobs.stage (extracting→transcribing→writing) + progress 0-100 → insert transcript + segments → videos.status=done. Errors → jobs.error, status=failed, 1 retry.
3. Frontend subscribes to Supabase Realtime on `jobs` for live status.
4. Auth: supabase-js on frontend (anon key); FastAPI validates JWTs; service-role key used ONLY server-side (app/worker LXCs).

## Networks
- All LXCs on vmbr0, 192.168.1.0/24, gw 192.168.1.1. Static IPs .201-.205.
- NFS: host bind-mount pattern (unprivileged CTs cannot mount NFS directly).
- GPU: /dev/nvidia0 → 204, /dev/nvidia1 → 205 (cgroup2 allow + bind mounts; uvm major changes on host reboot - recheck after driver updates).

## Constraints
- P4 = Pascal sm_61: INT8 only (DP4A), never FP16. Driver 550.163.01 (Debian non-free), kernel pinned 6.14.11-9-pve (550 can't build on 7.x). CT userland: 550 libs copied host→NFS→/usr/local (bookworm pkgs cap at 535). cublas/cudnn via pip cu12 wheels.
- Supabase trimmed: analytics/logs overlay, functions/deno-cache, supavisor disabled.
