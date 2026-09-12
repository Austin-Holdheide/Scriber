# Scriber Runbook (neo + LXCs)

## Startup order (after host reboot — all automatic, verify with scriber-status.sh)
1. NFS mounts on host (fstab: `/mnt/transcriber-nfs`)
2. LXCs 201→205 in startup order (onboot=1)
3. Supabase compose auto-starts (restart: unless-stopped)
4. systemd: transcriber-api (202), redis + rq-worker@203 (203), rq-worker@204/205

## Daily driver
- **Status:** `bash /root/scriber-status.sh`
- **Studio:** http://192.168.1.201:8000 · **API:** http://192.168.1.202/

## Common failures & fixes (learned the hard way)

| Symptom | Cause | Fix |
|---|---|---|
| GPU gone after CT restart | stale `/dev/nvidia-uvm` bind (uvm major drifts across host reboots) | `pct stop 204 && pct start 204` (re-evaluates mounts); majors currently 195 (nvidia*) / 510 (uvm) |
| Worker won't start: "active worker named 'scriber-worker-204' already" | SIGKILL left zombie registration | `pct exec 203 -- redis-cli del rq:worker:scriber-worker-204` then restart unit |
| Jobs vanish into 'queued' forever (older logs: TypeError missing arg) | RQ 2.12 treats `job_id` as RESERVED kwarg | use `job_row_id` (fixed in repo); after any producer fix, flush: `redis-cli --scan --pattern 'rq:*' \| xargs redis-cli del` |
| postgrest-py APIError "Missing response 204" | `.maybe_single()` on no-match | use `.limit(1).execute()` + check `len(data)` (fixed in repo) |
| Supabase containers unhealthy after reboot | normal transient | wait ~60s; restart policy handles it |
| unprivileged CT can't mount NFS (EPERM) | kernel blocks mount() in userns | host-mount + `mp0` bind (already configured) |
| DKMS breaks package configure on kernel upgrade | 550 can't build on 7.x kernels | NEVER install 7.x `proxmox-headers` on neo; kernel pinned 6.14.11-9-pve |

## Deploy procedures

### Backend (202)
```bash
# from repo root: tar backend/, scp to neo, then:
pct push 202 /tmp/sb.tar.gz /tmp/sb.tar.gz
pct exec 202 -- bash -c 'cd /opt/scriber && tar xzf /tmp/sb.tar.gz && systemctl restart transcriber-api'
```

### Workers (203/204/205)
Same push/extract, then `systemctl restart rq-worker@<id>`.
**After any host driver update:** re-stage libs to `/mnt/transcriber-nfs/.nvidia-libs-550/`
(new version!) and re-copy into both GPU CTs (`cp /mnt/media/.nvidia-libs-550/lib* /usr/local/lib/ && ldconfig`).

### Config
- 202/203/204/205: `/opt/scriber/.env` (chmod 600) — service key, device, model per CT
- 201: `/root/supabase-project/.env` — all Supabase secrets (backed up to TrueNAS)
- Caddy: 202 `/etc/caddy/Caddyfile`

## Backups
- Supabase `.env` → TrueNAS `config/` (manual, done W2)
- Supabase DB: nightly `pg_dump` planned W13; TrueNAS snapshots cover media
- Repo: github.com/Austin-Holdheide/Scriber (public — no secrets, ever)

## Recovery
- Worker CT: wipe venv → redeploy tar → restart unit (documented stack, ~5 min)
- Supabase: compose down/up in `/root/supabase-project`; DB is on 201 rootfs (vzdump covers it)

## W8-W11 additions (learned from real files)

| Symptom | Cause | Fix |
|---|---|---|
| Media plays "no supported format" though file is fine | `<audio>/<video>` can't send Authorization headers → 401 | signed media-token: GET `/api/videos/{id}/media-token` then `?mt=&mu=` on the src (implemented in VideoPage) |
| MEDIA_ELEMENT_ERROR on correctly-named file | extension lies (jfk.flac uploaded as .wav) | download endpoint sniffs magic bytes for Content-Type |
| Every segment highlights at once | transcript endpoint returned segments WITHOUT id | select id (fixed); always include PKs in selects |
| Transcript ends early / "desyncs" past N min | PostgREST 1000-row silent cap | transcript endpoint pages with Range headers |
| Transcript drifts worse the longer it plays | faster-whisper VAD remap error on long files | VAD only < 10min; long files transcribe without VAD |
| Both GPU workers OOM-killed on long file | whole-file decode ~850MB float32 for 3.7h audio | 10-min chunked transcription (constant RAM), committed fad3a01 |
| Download 500 on some files | unicode filename (full-width ？) breaks latin-1 headers | RFC 5987: ascii fallback + filename*=UTF-8'' |
| Job frozen mid-stage after worker restart/crash | RQ orphans the DB row on hard kill | `scriber-requeue.timer` on 202: requeues any job with no heartbeat > 3 min |
| CPU worker "steals" jobs from GPUs | all workers raced one queue | GPU workers listen [transcribe-gpu, transcribe]; CPU only [transcribe]; API enqueues to transcribe-gpu |

## Media tokens (for <audio>/<video>)
- `GET /api/videos/{id}/media-token` (JWT) → `{token: "<expires>:<hmac>"}`
- Player src: `/api/videos/{id}/download?mt=<token>&mu=<user_id>`
- HMAC is over video_id + user_id + expiry, secret = SUPABASE_JWT_SECRET (202 .env)
- TTL 10 min; stateless (no shared storage needed across uvicorn workers)
- If playback 401s later: check SUPABASE_JWT_SECRET is non-empty on 202 (it was once empty — W8 bug)

## Frontend build
```bash
# on 202, with env at build time (anon key is public-by-design):
cd /opt/scriber/frontend
VITE_SUPABASE_URL=http://192.168.1.201:8000 VITE_SUPABASE_ANON_KEY=<anon> npm run build
# dist/ served by Caddy; SPA fallback via try_files
```
