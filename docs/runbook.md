# Scriber Runbook (neo + LXCs)

## Startup order (after host reboot)
NFS is an AUTOMOUNT now (mounts on first access) and LXCs are onboot=1, so startup is
mostly automatic. GPU workers are the one exception - see "After host reboot" below.

### After host reboot (GPU recovery)
1. `nvidia-smi` on the HOST once (udev creates /dev/nvidia-uvm; nvidia_uvm major DRIFTS per boot - was 510, now 511)
2. `pct restart 204 205` (bind mounts re-evaluate; SERVICE restarts are not enough)
3. verify: `pct exec 204 -- ls -la /dev/nvidia-uvm` shows a real device (not a 0-byte dummy)
4. verify CUDA: `pct exec 204 -- /opt/scriber/venv/bin/python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"`

Why: CTs that boot before the host uvm node exists bind EMPTY dummy files -> CUDA
"unknown error". cgroup2 allow lines in 204/205.conf cover majors 195:* and 511:*.

## Daily driver
- **Status:** `bash /root/scriber-status.sh`
- **Studio:** http://192.168.1.201:8000 - **API:** http://192.168.1.202/
- **ntfy:** http://192.168.1.203:9095 (user `scriber`, topics `scriber-*`)

## Common failures & fixes (learned the hard way)

| Symptom | Cause | Fix |
|---|---|---|
| "source missing" on jobs after reboot; /mnt/media empty in CTs | NFS mount timed out at boot (TrueNAS not ready), systemd marked failed and never retried | FIXED 9/16: fstab uses `x-systemd.automount,nofail,x-systemd.mount-timeout=30` - mounts on first access. Old-style manual fix: `systemctl start 'mnt-transcriber\x2dnfs.mount'` |
| CUDA "failed with error unknown error" | CT booted before host /dev/nvidia-uvm existed -> dummy file bound; or uvm major changed | see "After host reboot" above |
| GPU gone after CT restart | stale `/dev/nvidia-uvm` bind | `pct stop 204 && pct start 204` (re-evaluates mounts) |
| Worker won't start: "active worker named 'scriber-worker-204' already" | SIGKILL left zombie registration | `pct exec 203 -- redis-cli del rq:worker:scriber-worker-204` then restart unit |
| Frontend blank page after npm build | `.env.local` missing -> VITE_SUPABASE_* undefined -> supabase-js throws at boot | `/opt/scriber/frontend/.env.local` must exist with VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY before `npm run build` |
| Copy button does nothing on LAN | navigator.clipboard is HTTPS-only | implemented execCommand fallback (lib/clipboard.ts); button shows "select + Ctrl+C" if even that fails |
| postgrest-py APIError "Missing response 204" | `.maybe_single()` on no-match | use `.limit(1).execute()` + check `len(data)` |
| Supabase containers unhealthy after reboot | normal transient | wait ~60s; restart policy handles it |
| DKMS breaks package configure on kernel upgrade | 550 can't build on 7.x kernels | NEVER install 7.x `proxmox-headers` on neo; kernel pinned 6.14.11-9-pve |
| Transcript ends early / desyncs | PostgREST 1000-row silent cap | transcripts + pdf/docx artifact paths page with Range headers (`_all_segments`) |
| PDF export 500 "Not enough horizontal space" | fpdf2 multi_cell + over-long token | soft-wrap in pdf_export.py (fixed); delete stale PDFs to force regen |
| ntfy publish 403 | auth deny-all; grant is set-not-add | `ntfy access scriber 'scriber-*' read-write` (single word - `wr` invalid) |

## Deploy procedures

### Backend (202)
```bash
# from repo root: tar backend/, scp to neo, then:
pct push 202 /tmp/sb.tar.gz /tmp/sb.tar.gz
pct exec 202 -- bash -c 'cd /opt/scriber && tar xzf /tmp/sb.tar.gz && systemctl restart transcriber-api'
```

### Workers (203/204/205)
Same push/extract, then `systemctl restart rq-worker@<id>`.
Worker CTs need: app/workers/tasks.py + app/services/notify.py + app/services/thumbs.py
(they do NOT need the API routers).
**After any host driver update:** re-stage libs to `/mnt/transcriber-nfs/.nvidia-libs-550/`
and re-copy into both GPU CTs (`cp /mnt/media/.nvidia-libs-550/lib* /usr/local/lib/ && ldconfig`).

### Frontend (202)
```bash
# .env.local (chmod 600) MUST exist first - missing VITE_* = blank page
pct exec 202 -- bash -c 'cd /opt/scriber/frontend && npm run build'
# dist/ served by Caddy; SPA fallback via try_files
```

### SQL migrations
```bash
# psql inside supabase-db container on 201:
pct push 201 migrations/0005_search_hybrid.sql /tmp/m.sql
pct exec 201 -- sh -c 'docker exec -i supabase-db psql -U supabase_admin -d postgres < /tmp/m.sql'
```

### Config
- 202/203/204/205: `/opt/scriber/.env` (chmod 600) - service key, device, model per CT
- 202: `/opt/scriber/frontend/.env.local` (chmod 600) - VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
- 201: `/root/supabase-project/.env` - all Supabase secrets (backed up to TrueNAS)
- ntfy: 203 `/etc/ntfy/server.yml` (deny-all; user scriber; see observability/ntfy-server.yml.example)
- Caddy: 202 `/etc/caddy/Caddyfile`

## Backups
- Proxmox vzdump: nightly 04:00 zstd, CTs 201-205 -> neoDATA, keep-last=3 (verified)
- Supabase `.env` -> TrueNAS `config/`
- Supabase DB: pg_dump drill still open (W13); TrueNAS snapshots cover media
- Grafana dashboards: PC + TrueNAS /backups/grafana/
- Repo: github.com/Austin-Holdheide/Scriber (public - no secrets, ever)

## W12/cheap-wins additions

| Symptom | Cause | Fix |
|---|---|---|
| Cancel not converging while worker alive | worker heartbeats rewrite `stage` every 5s | dedicated `jobs.cancel_requested` boolean; heartbeats check + raise JobCancelled |
| Double-enqueue after crash (job runs twice) | RQ default random ids | deterministic job id `scriber-<job_row_id>` + pre-enqueue delete of leftovers |
| Thumbnail missing on old uploads | feature added later | `scripts/backfill_thumbs.py` on 202 (idempotent, skips existing) |
| Share page / media 404 for viewers | token expired or revoked | create a new link; revocation is immediate on every public request |

## Media tokens (for <audio>/<video>)
- `GET /api/videos/{id}/media-token` (JWT) -> `{token: "<expires>:<hmac>"}`
- Player src: `/api/videos/{id}/download?mt=<token>&mu=<user_id>`
- HMAC over video_id + user_id + expiry, secret = SUPABASE_JWT_SECRET (202 .env); TTL 10 min
- Thumbnails use the same scheme: `POST /api/videos/thumb-tokens` (batch) -> `?mt=&mu=` per <img>
