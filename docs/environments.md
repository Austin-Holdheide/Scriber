# Environments

Scribly runs two independent stacks on the same Proxmox host (`neo`). They share hardware and nothing
else — no database, no Redis, no media directory, no JWT keys, no frontend bundle.

| | **prod** | **dev** |
|---|---|---|
| Host / CTs | neo 201, 202, 203, 204, 205 | neo **206** (`vm206-scribly-dev`) |
| Address | 192.168.1.201–.205 (+ `pocscribly.holdheide.com`, `db.scribly.cc`) | **192.168.1.226** (LAN only until DNS/TLS is wired) |
| Supabase | 201 — 9 containers | 206 — 9 containers, own keys and DB |
| API | 202 `transcriber-api` :8001 | 206 `transcriber-api-dev` :8002 |
| Frontend | Caddy :80 on 202 (`/opt/scriber/frontend/dist`) | nginx :80 on 206 (`/var/www/scribly-dev`, `/api/` → :8002) |
| Redis / queues | 203 | 206, `127.0.0.1` |
| Workers | `rq-worker@203` (CPU), `rq-worker@204/205` (P4s) | `rq-worker-dev` (CPU, always on), `rq-worker-dev-gpu` (**disabled** — opt-in P4) |
| Media | `neoDATA/media` → `/mnt/media` | `neoDATA/dev/media` → `/mnt/media` |
| DB data | docker volume on 201 | `neoDATA/dev/pgdata` (own dataset, snapshot-able) |
| Code | `/opt/scriber` | `/opt/scriber-dev` |
| Secrets | `/root/supabase-project/.env` on 201 | `/opt/supabase/.env` on 206 |

**Never reuse a prod key in dev.** The dev key set was generated fresh with
`utils/generate-keys.sh --update-env` + `utils/add-new-auth-keys.sh --update-env`; 18 secret values are
compared against prod's and must report `SHARED_WITH_PROD: none`. A dev JWT must not authenticate
against prod (`db.scribly.cc`) or vice versa.

## Seeding dev

Dev was initialised by restoring the **nightly prod `pg_dump`** (`/mnt/media/pg/scribly-<date>.sql.gz`)
— which doubles as the restore drill. For a clean import:

```bash
docker exec supabase-db psql -U postgres -d postgres -c "drop schema if exists public cascade; create schema public;"
zcat scribly-<date>.sql.gz | docker exec -i supabase-db psql -U postgres -d postgres
```
"already exists" errors for `auth` / `storage` / `realtime` / `extensions` are expected; the data lands.
Do **not** pipe the restore through `grep | head` — the broken pipe truncates the import (symptom:
`videos = 0` while `auth.users = 3`).

Re-applying `anon`/`authenticated` grants after a restore is still outstanding — PostgREST returns 403 on
`/rest/v1/` in dev until then. The app itself is unaffected (the API uses the service key).

## GPU in dev (opt-in)

CT 206 has `dev0: /dev/nvidia0` plus the nvidiactl/uvm binds and prod's driver + cuBLAS/cuDNN libs, so
`ctranslate2.get_cuda_device_count()` reports `1`. The GPU worker is **not** enabled:

```bash
pct exec 206 -- systemctl start rq-worker-dev-gpu    # uses the shared P4 against dev DB/Redis/media
pct exec 206 -- systemctl stop  rq-worker-dev-gpu
```
Prod is untouched either way — dev jobs cannot land in prod queues because the Redis brokers are separate.

## Changing the dev IP

Four things bake the address; change all of them or you get a page that loads but cannot authenticate:

1. `pct set 206 -net0 …,ip=192.168.1.226/24` then `pct stop/start 206`
2. `/opt/supabase/.env` → `API_EXTERNAL_URL`, `SITE_URL`
3. `/opt/scriber-dev/.env` → `SUPABASE_URL`, `CORS_ORIGINS`
4. rebuild the dev bundle with `VITE_SUPABASE_URL=<new>` and redeploy to `/var/www/scribly-dev`, then
   `docker compose up -d --force-recreate` on 206 so auth/envoy pick up the new URLs

Verify the bundle: new URL present (≥1), the old IP absent (0), `db.scribly.cc` absent (0).

## Addresses already taken

`192.168.1.206` is the **iDRAC** — do not assign it. Dev started there and was moved to `.226`.
