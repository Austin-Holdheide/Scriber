# Scriber — Architecture

## Components
```
[Browser / curl]
   |  HTTP (LAN, TLS in W16)
   v
[Caddy :80 - LXC 202 "app"]  (5GB cap; serves React SPA from dist/, proxies /api/*)
   |-- /            -> static React build (frontend/dist)
   +-- /api/*       -> uvicorn FastAPI (127.0.0.1:8001, 2 workers)
                         |
                         |-- supabase-py (service key) --> [Supabase - LXC 201 :8000 via Kong]
                         |                                    |- Postgres (videos/transcripts/segments/jobs/share_links)
                         |                                    |- Auth (GoTrue), REST (PostgREST), Realtime, Storage
                         |-- RQ enqueue --> [Redis :6379 - LXC 203 "worker"]
                         |-- thumbnails (ffmpeg, shared services/thumbs.py)
                         |-- ntfy HTTP push (job done/failed/cancelled)
                                                |
                                 +--------------+--------------+
                                 v                             v
                          [RQ CPU worker 203]         [RQ GPU workers 204/205]
                          faster-whisper int8          faster-whisper int8 CUDA
                          14 threads                   P4 #0 / P4 #1
                                 +--------------+--------------+
                                                v
                              ffmpeg -> 16k mono wav -> ASR -> segments
                                                |
                                                v
                    TrueNAS NFS 192.168.1.116:/mnt/main/transcriber
                    (host AUTOMOUNT /mnt/transcriber-nfs - mounts on first access,
                     bind-mounted as /mnt/media in 202-205)
```

## Data flow
1. Upload: browser -> Caddy /api/videos/upload -> FastAPI streams to /mnt/media/videos/{user_id}/{uuid}.{ext}
   -> insert `videos` row -> insert `jobs` row -> enqueue RQ job (deterministic id `scriber-<job_row_id>`).
   Thumbnail grabbed in a background thread right after the upload lands.
2. Worker picks up: health gate (ffprobe) -> thumbnail (if missing) -> stages extracting/transcribing/writing
   with 5s heartbeats. Each heartbeat also checks `jobs.cancel_requested` -> raises JobCancelled -> row converges
   to cancelled. Chunked 10-min transcription -> transcript + segments + SRT/VTT on NFS -> done.
   ntfy push to the owner's topic on done/failed/cancelled (non-fatal).
3. Re-transcribe: deletes old transcript (segments cascade) + artifacts, new jobs row, re-enqueue.
4. Share links: owner creates token (1-30d expiry, revocable). Public endpoints
   (`/api/videos/public/{token}[/media|/thumb|/artifact/{kind}]`) authorize by token only -
   transcript + player + downloads, no account. Revocation/expiry is checked on every request.
5. Frontend subscribes to Supabase Realtime on `jobs` for live status (list + video page).
6. Auth: supabase-js on frontend (anon key); FastAPI validates JWTs via JWKS; service-role key
   ONLY server-side (202/203/204/205 .env). Media for <audio>/<video> uses signed ?mt=&mu= tokens.

## Search (hybrid, migration 0005)
`search_segments_for_user(query, user)` = FTS matches (ts_rank ordered) UNION prefix matches
(`word:*` to_tsquery) UNION substring matches (ilike >=3 chars), deduped, limit 200.
Fixes: "search" now surfaces research/researchers/unsearchable; partial words ("transcri") match.

## Networks
- All LXCs on vmbr0, 192.168.1.0/24, gw 192.168.1.1. Static IPs .201-.205.
- NFS: HOST automount (`x-systemd.automount,nofail` in fstab, mounts on first access - survives
  boot races with TrueNAS) + `mp0` bind into 202-205 (unprivileged CTs cannot mount NFS).
- GPU: /dev/nvidia0 -> 204, /dev/nvidia1 -> 205. cgroup2 allow = `c 195:* rwm` + `c 511:* rwm`
  (uvm major DRIFTS across host reboots: was 510, now 511). After any host reboot:
  run `nvidia-smi` once on the host (udev creates /dev/nvidia-uvm), then `pct restart 204 205`.
  Service restarts do NOT rebind - the CT must restart while the host node exists.
- ntfy: LXC 203 :9095, auth deny-all, user `scriber` read-write on `scriber-*` topics.
  Topic per user: `scriber-<first 10 chars of user id, dashes stripped>`.
