#!/usr/bin/env bash
# Weekly off-box copy of Scribly media to TrueNAS (cold backup).
# Mounts the export ONLY for the run, verifies it really is NFS before writing,
# and never blocks when the NAS is down (soft mount + timeouts).
set -uo pipefail
SRC=/neoDATA/media
DST=/mnt/transcriber-nfs
EXPORT=192.168.1.116:/mnt/main/transcriber
LOG=/var/log/scribly-offsite.log
exec >>"$LOG" 2>&1
echo "=== $(date -Is) offsite start"

mounted_nfs() { findmnt -T "$DST" -no FSTYPE 2>/dev/null | grep -qx nfs; }

# 1. already mounted?
if ! mounted_nfs; then
  # 2. is the NAS there at all?
  if ! timeout 5 bash -c '</dev/tcp/192.168.1.116/2049' 2>/dev/null; then
    echo "SKIP: TrueNAS 192.168.1.116:2049 unreachable — cold copy left as-is"
    exit 0
  fi
  mkdir -p "$DST"
  timeout 60 mount -t nfs -o rw,noatime,soft,timeo=30,retrans=2,vers=3 "$EXPORT" "$DST" \
    || { echo "SKIP: mount failed"; exit 0; }
fi

# 3. HARD GUARD: never rsync into the local root disk because a mount went missing
if ! mounted_nfs; then
  echo "ABORT: $DST is not NFS (would have written to local disk) — nothing copied"; exit 1
fi

for d in videos hf-cache backups; do
  [ -d "$SRC/$d" ] || continue
  echo "-- rsync $d"
  timeout 3600 rsync -a --delete --no-o --no-g "$SRC/$d/" "$DST/$d/" || echo "WARN: rsync $d rc=$?"
done

echo "=== $(date -Is) offsite done; dest: $(findmnt -T $DST -no SOURCE) $(du -sh $DST | cut -f1) used"

# 4. release the mount again (cold backup should not sit mounted)
timeout 120 umount "$DST" && echo "unmounted" || echo "WARN: umount deferred"
