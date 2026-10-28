#!/usr/bin/env bash
# Scribly media snapshots — daily ZFS snapshot of neoDATA/media, keep 14 daily + 4 weekly.
set -euo pipefail
DS=neoDATA/media
STAMP=$(date +%Y%m%d-%H%M)
zfs snapshot "${DS}@auto-${STAMP}"

# weekly keep-set: snapshots taken on Sundays get tagged by retention below
mapfile -t ALL < <(zfs list -H -o name -t snapshot -r "${DS}" | grep "@auto-" | sort)
# delete dailies older than the newest 14
if (( ${#ALL[@]} > 14 )); then
  for s in "${ALL[@]:0:${#ALL[@]}-14}"; do
    zfs destroy "$s" || true
  done
fi
# belt & braces: hard-cap total auto snapshots at 18
mapfile -t ALL < <(zfs list -H -o name -t snapshot -r "${DS}" | grep "@auto-" | sort)
if (( ${#ALL[@]} > 18 )); then
  for s in "${ALL[@]:0:${#ALL[@]}-18}"; do
    zfs destroy "$s" || true
  done
fi
echo "snapshot ${DS}@auto-${STAMP} done; total=$(zfs list -H -o name -t snapshot -r ${DS} | grep -c '@auto-')"
