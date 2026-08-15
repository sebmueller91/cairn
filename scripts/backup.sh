#!/bin/bash
# Runs from host cron on the Pi (ADR 0009: backup stays decoupled from the
# API container's own health). Two layers per spec 6.6:
#   1. SQLite .backup + integrity_check (survives the live WAL file being
#      mid-write; a plain `cp` would not).
#   2. Logical export via the API itself (survives a schema/app change the
#      raw .db file wouldn't).
# Local retention is a placeholder (14 days) until the offsite 3-2-1 layer
# exists — this directory alone is not the real backup, just the local
# leg of it.
set -euo pipefail

DATA_DIR=/srv/cairn/data
BACKUP_DIR=/srv/cairn/backups
ENV_FILE=/srv/cairn/config/.env
DB_FILE="$DATA_DIR/cairn.db"
TODAY=$(date +%F)
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"

backup_ok=false
integrity_ok=false
export_ok=false

if sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/cairn-$TODAY.db'"; then
  backup_ok=true
  result=$(sqlite3 "$BACKUP_DIR/cairn-$TODAY.db" "PRAGMA integrity_check;")
  if [ "$result" = "ok" ]; then
    integrity_ok=true
  fi
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

if [ "$backup_ok" = true ] && [ "$integrity_ok" = true ]; then
  if curl -sf -o "$BACKUP_DIR/cairn-export-$TODAY.zip" \
      -H "Authorization: Bearer $API_TOKEN" \
      "https://localhost/api/export/full" --insecure; then
    export_ok=true
  fi
fi

timestamp=$(date -Iseconds)
cat > "$BACKUP_DIR/latest_run.json" <<EOF
{"timestamp": "$timestamp", "backup_ok": $backup_ok, "integrity_ok": $integrity_ok, "export_ok": $export_ok}
EOF

# Only updated on a fully clean run — this file's own timestamp going
# stale *is* the failure signal /api/health and the data quality panel
# read (spec 6.6: "warns when the last successful backup is older than
# 48 hours"), rather than trying to push an alert the moment something
# breaks (ADR 0012: deliberately deferred).
if [ "$backup_ok" = true ] && [ "$integrity_ok" = true ] && [ "$export_ok" = true ]; then
  echo "$timestamp" > "$BACKUP_DIR/last_success"
fi

find "$BACKUP_DIR" -maxdepth 1 -name 'cairn-*.db' -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -name 'cairn-export-*.zip' -mtime "+$RETENTION_DAYS" -delete

if [ "$backup_ok" = true ] && [ "$integrity_ok" = true ] && [ "$export_ok" = true ]; then
  echo "backup ok: $timestamp"
else
  echo "backup FAILED: backup_ok=$backup_ok integrity_ok=$integrity_ok export_ok=$export_ok" >&2
  exit 1
fi
