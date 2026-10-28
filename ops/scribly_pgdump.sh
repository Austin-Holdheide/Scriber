#!/usr/bin/env bash
# Nightly pg_dump of the Supabase database to the media dataset (W13).
# Install on CT 201 as /usr/local/bin/scribly-pgdump.sh, cron: 30 3 * * *
set -uo pipefail

OUT_DIR="${OUT_DIR:-/mnt/media/pg}"
KEEP_DAYS="${KEEP_DAYS:-7}"
OUT="$OUT_DIR/scribly-$(date +%F).sql.gz"

mkdir -p "$OUT_DIR"

docker exec supabase-db pg_dump -U postgres -d postgres --no-owner \
  | gzip -9 > "$OUT.tmp" \
  && mv "$OUT.tmp" "$OUT" \
  || { rm -f "$OUT.tmp"; echo "pg_dump failed" >&2; exit 1; }

find "$OUT_DIR" -name 'scribly-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "pg_dump ok: $OUT ($(stat -c%s "$OUT") bytes), kept=$(ls -1 "$OUT_DIR"/scribly-*.sql.gz | wc -l)"
