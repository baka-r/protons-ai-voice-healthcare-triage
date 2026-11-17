#!/bin/sh
# PostgreSQL backups.  Usage:  backup.sh once | backup.sh loop
# Dumps to /backups/triage-YYYYmmdd-HHMMSS.sql.gz and deletes dumps older than KEEP_DAYS.
set -eu
KEEP_DAYS="${KEEP_DAYS:-14}"
dump() {
  f="/backups/triage-$(date +%Y%m%d-%H%M%S).sql.gz"
  pg_dump --no-owner --clean --if-exists | gzip -9 > "$f.tmp" && mv "$f.tmp" "$f"
  find /backups -name 'triage-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
  echo "backup ok: $f ($(du -h "$f" | cut -f1))"
}
case "${1:-once}" in
  once) dump ;;
  loop) while true; do dump || echo "backup FAILED" >&2; sleep 86400; done ;;
  *) echo "usage: $0 once|loop" >&2; exit 2 ;;
esac
