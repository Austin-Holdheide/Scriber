# Ops scripts

Host-side and container-side jobs that protect Scribly's data. Everything here is deployed and running
on **neo** as of 2026-10-28; keep this directory as the source of truth and re-push after editing.

| File | Installed at | Schedule | What it does |
|---|---|---|---|
| `scribly_media_snapshot.sh` | `/usr/local/sbin/` on neo + `systemd` timer `scribly-media-snapshot.timer` | daily 03:15 | `zfs snapshot neoDATA/media@auto-<ts>`, keeps newest 14 (hard cap 18) — recovers a deleted video in one command |
| `scribly_media_offsite.sh` | `/usr/local/sbin/` on neo + `scribly-media-offsite.timer` | Sun 05:00 | mounts the TrueNAS export, `rsync -a --delete` videos + hf-cache + backups, unmounts; **skips** when the NAS is unreachable and **aborts** if the mount silently didn't happen |
| `scribly_pgdump.sh` | `/usr/local/bin/` on **CT 201**, cron `30 3 * * *` | daily 03:30 | gzipped `pg_dump --no-owner` → `/mnt/media/pg/scribly-<date>.sql.gz`, keeps 7 days |

## Why the offsite script is defensive

`/mnt/transcriber-nfs` stopped being an automount when media moved to the local ZFS dataset
(2026-10-27). A naive `rsync $SRC/ $DST/` then writes the entire media set onto neo's **root disk**
(39 GB, hit 82% once). The script therefore:

1. probes TCP 2049 before doing anything,
2. mounts the export explicitly (soft, bounded),
3. verifies `findmnt -T $DST -no FSTYPE` reports `nfs` and **aborts** if not,
4. unmounts when finished so the NAS is not a live dependency.

## Restore drills

- Media: `zfs list -t snapshot -r neoDATA/media` → `zfs clone`/`send|recv` a snapshot, or copy the one file back.
- Database: `zcat /mnt/media/pg/scribly-<date>.sql.gz | docker exec -i supabase-db psql -U postgres -d postgres`
  (drop/recreate `public` first for a clean import; "already exists" errors for auth/storage/realtime are expected).
  This path was proven 2026-10-27 by restoring the nightly dump into the new dev environment.
