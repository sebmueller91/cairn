#!/bin/bash
# Runs from host cron on the Pi (ADR 0009: backup stays decoupled from the
# API container's own health). Three layers per spec 6.6:
#   1. SQLite .backup + integrity_check (survives the live WAL file being
#      mid-write; a plain `cp` would not).
#   2. Logical export via the API itself (survives a schema/app change the
#      raw .db file wouldn't).
#   3. Offsite copy to the NAS over an SMB mount (ADR 0015). This is the
#      leg that survives the Pi itself being dead or stolen — until it
#      existed, /srv/cairn/backups was one device away from total loss.
set -euo pipefail

# Paths are overridable only so the offsite leg can be exercised against a
# scratch directory without a real NAS (scripts/test-backup.sh). Cron passes
# nothing and gets the real ones.
DATA_DIR=${DATA_DIR:-/srv/cairn/data}
BACKUP_DIR=${BACKUP_DIR:-/srv/cairn/backups}
ENV_FILE=${ENV_FILE:-/srv/cairn/config/.env}
EXPORT_URL=${EXPORT_URL:-https://raspberrypi5/api/export/full}
DB_FILE="$DATA_DIR/cairn.db"
TODAY=$(date +%F)
RETENTION_DAYS=14

# Content plausibility floor for the "content" leg of layer 1's integrity
# check (see below). Deliberately schema-agnostic (>=1, not tied to the
# app's current table count) so this doesn't need updating every time a
# migration adds a table: an empty-but-structurally-valid database — which
# is exactly what `sqlite3 "$DB_FILE" ".backup ..."` silently produces when
# $DB_FILE doesn't exist yet — has zero tables. Any real database, migrated
# or not, has at least one.
MIN_TABLE_COUNT=1

# The SMB share (ADR 0015). NAS_MOUNT is the mountpoint itself; everything
# this script writes lives under NAS_DIR so the share can hold other things
# without this script's retention ever looking at them.
NAS_MOUNT=${NAS_MOUNT:-/srv/cairn/nas}
NAS_DIR="$NAS_MOUNT/cairn"
NAS_DB_DIR="$NAS_DIR/db"
NAS_EXPORT_DIR="$NAS_DIR/exports"
NAS_PRE_DIR="$NAS_DIR/pre-migration"

# Offsite retention. Deliberately far more generous than spec 6.6's
# 7/4/12: at this data size 50 GB holds years, so the binding constraint
# isn't space, it's *reach*. Slow corruption surfaces weeks or months
# later, at which point the copy that saves you is an old one — more
# recent copies of an already-corrupt file protect nothing.
NAS_DAILY_DAYS=180    # every night for half a year
NAS_MONTHLY_DAYS=1825 # first-of-month snapshots for five years
NAS_PRE_DAYS=365      # deploy-time (pre-migration) snapshots

mkdir -p "$BACKUP_DIR"

backup_ok=false
integrity_ok=false
content_ok=false
export_ok=false
offsite_ok=false

# --- Pre-flight: refuse to "back up" a database that isn't there --------
#
# `sqlite3 "$DB_FILE" ".backup ..."` CREATES $DB_FILE if it does not
# exist — e.g. because the /srv/cairn/data bind mount failed to come up
# after a reboot — and the resulting empty 4096-byte database passes
# PRAGMA integrity_check (an empty database IS structurally valid). Every
# guard below checks *structure*, not *content*, so without this check
# backup_ok and integrity_ok both go true, both success markers get
# written, and the empty file mirrors to the NAS where it passes the
# NAS-side integrity check too. Reproduced end to end against an empty
# data dir. Must run before the `.backup` call, not after.
if [ ! -f "$DB_FILE" ]; then
  echo "backup: $DB_FILE does not exist — refusing to back up (this would silently create an empty DB)" >&2
  exit 1
fi
if [ ! -s "$DB_FILE" ]; then
  echo "backup: $DB_FILE exists but is empty — refusing to back up" >&2
  exit 1
fi

if sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/cairn-$TODAY.db'"; then
  backup_ok=true
  result=$(sqlite3 "$BACKUP_DIR/cairn-$TODAY.db" "PRAGMA integrity_check;")
  if [ "$result" = "ok" ]; then
    integrity_ok=true
  fi
fi

# Content plausibility, on top of the pre-flight check above: the source
# could still be swapped out for an empty-but-otherwise-fine database
# between the pre-flight check and `.backup` running (or the pre-flight
# check alone doesn't prove the *backup* isn't degenerate) — this checks
# the thing that was actually produced, not just the thing it was read
# from.
if [ "$backup_ok" = true ] && [ "$integrity_ok" = true ]; then
  table_count=$(sqlite3 "$BACKUP_DIR/cairn-$TODAY.db" \
    "SELECT count(*) FROM sqlite_master WHERE type='table';")
  if [ "$table_count" -ge "$MIN_TABLE_COUNT" ]; then
    content_ok=true
  else
    echo "backup: cairn-$TODAY.db has only $table_count tables (floor: $MIN_TABLE_COUNT) — treating as a failed backup" >&2
  fi
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

if [ "$backup_ok" = true ] && [ "$integrity_ok" = true ] && [ "$content_ok" = true ]; then
  # Caddy's site blocks are matched by Host/SNI, not by which local
  # address the connection came in on — a request to "localhost" (or any
  # other name not in the Caddyfile's site list) doesn't match anything
  # and gets a bare, silent 200 with an empty body, not an error. Found
  # live: `curl -f` alone treated that as success. Must be one of the
  # actual configured names, and the body must be positively checked too,
  # not just the HTTP status.
  #
  # The token is passed via `-K -` (a config file read from stdin) rather
  # than `-H "Authorization: Bearer $API_TOKEN"` on the command line —
  # command-line arguments are readable via `ps auxww` by any local user
  # for the duration of the request. `-K -`'s "header" directive achieves
  # the same header without it ever appearing in argv.
  export_zip="$BACKUP_DIR/cairn-export-$TODAY.zip"
  if printf 'header = "Authorization: Bearer %s"\n' "$API_TOKEN" \
      | curl -sf -K - -o "$export_zip" "$EXPORT_URL" --insecure \
      && [ -s "$export_zip" ] \
      && python3 -c "import zipfile,sys; sys.exit(0 if zipfile.is_zipfile(sys.argv[1]) else 1)" "$export_zip"; then
    export_ok=true
  fi
fi

# --- Layer 3: offsite to the NAS ------------------------------------------
#
# Never mirrors a file that failed its own integrity check — a faithfully
# copied corrupt database is worse than no copy, because it looks like a
# backup. Every command that touches the mount is wrapped in `timeout`:
# this runs from cron at 03:00 under `set -e`, and a wedged CIFS mount
# would otherwise hang the job indefinitely rather than fail it.
if [ "$backup_ok" = true ] && [ "$integrity_ok" = true ] && [ "$content_ok" = true ]; then
  # Reading the path is what triggers the automount; `mountpoint` alone
  # would prove nothing, because with an automount unit in place
  # /srv/cairn/nas is an autofs mountpoint whether or not the NAS is
  # actually reachable. The findmnt check is the one that matters: it
  # refuses to proceed unless a real CIFS filesystem is mounted there.
  # Writing into an unmounted directory would quietly fill the Pi's own
  # disk while looking, from every status file, like a successful
  # offsite backup — the exact silent failure this layer exists to end.
  if ! timeout 60 ls "$NAS_MOUNT" >/dev/null 2>&1; then
    echo "offsite: $NAS_MOUNT is not reachable, skipping" >&2
  elif ! timeout 10 findmnt --types cifs --target "$NAS_MOUNT" >/dev/null; then
    echo "offsite: $NAS_MOUNT is not a CIFS mount — refusing to write to local disk" >&2
  elif ! timeout 60 mkdir -p "$NAS_DB_DIR" "$NAS_EXPORT_DIR" "$NAS_PRE_DIR"; then
    echo "offsite: cannot create target directories on $NAS_MOUNT" >&2
  else
    # No --delete, ever. This is a backup, not a mirror: without it, a
    # script bug or an rm -rf on the Pi would be faithfully replicated to
    # the NAS at 03:00 and destroy the only surviving copy. The NAS side
    # only grows; its retention is the separate, gentler policy below.
    #
    # --include/--exclude rather than shell globs so a category with no
    # matching files (pre-migration snapshots, most nights) is a no-op
    # instead of an unmatched-glob error. -rt with perms/owner/group
    # suppressed because the CIFS mount forces its own uid/gid/mode and
    # rsync -a's chown would fail against it.
    rsync_opts=(-rt --no-perms --no-owner --no-group)
    rsync_ok=true
    timeout 900 rsync "${rsync_opts[@]}" \
      --include='cairn-????-??-??.db' --exclude='*' \
      "$BACKUP_DIR/" "$NAS_DB_DIR/" || rsync_ok=false
    timeout 900 rsync "${rsync_opts[@]}" \
      --include='cairn-export-*.zip' --exclude='*' \
      "$BACKUP_DIR/" "$NAS_EXPORT_DIR/" || rsync_ok=false
    # Deploy-time snapshots (scripts/deploy.sh) are part of the same
    # safety net and until now lived only on the Pi.
    timeout 900 rsync "${rsync_opts[@]}" \
      --include='pre-migration-*.db' --exclude='*' \
      "$BACKUP_DIR/" "$NAS_PRE_DIR/" || rsync_ok=false

    # Verify what actually landed, on the NAS side, rather than trusting
    # rsync's exit code — the export step above exists in its current
    # shape precisely because an exit code alone once reported a silent
    # false success in production. offsite_ok therefore also requires
    # export_ok: if today's export never got written locally there is
    # nothing to verify, and the run is already a failure anyway.
    nas_db="$NAS_DB_DIR/cairn-$TODAY.db"
    nas_zip="$NAS_EXPORT_DIR/cairn-export-$TODAY.zip"
    # immutable=1 rather than a plain open, for two reasons. It stops
    # SQLite creating a -wal/-shm pair beside the copy: locally those are
    # cleaned up on close, but on CIFS they are left behind, so a plain
    # open would strand a pair per night next to the very files a restore
    # picks from — and a stale WAL beside a database you are about to
    # restore is a genuine hazard (see Scenario A). It is also the more
    # honest check: `.backup` produces a fully checkpointed standalone
    # file, and immutable=1 verifies exactly that file, the way a restore
    # would actually use it, rather than the file plus whatever journal
    # happens to sit next to it.
    if [ "$rsync_ok" = true ] && [ "$export_ok" = true ] \
        && [ "$(timeout 300 sqlite3 "file:$nas_db?immutable=1" 'PRAGMA integrity_check;')" = "ok" ] \
        && timeout 120 python3 -c "import zipfile,sys; sys.exit(0 if zipfile.is_zipfile(sys.argv[1]) else 1)" "$nas_zip"; then
      offsite_ok=true
    else
      echo "offsite: copy did not verify on the NAS (rsync_ok=$rsync_ok export_ok=$export_ok)" >&2
    fi
  fi
fi

timestamp=$(date -Iseconds)
cat > "$BACKUP_DIR/latest_run.json" <<EOF
{"timestamp": "$timestamp", "backup_ok": $backup_ok, "integrity_ok": $integrity_ok, "content_ok": $content_ok, "export_ok": $export_ok, "offsite_ok": $offsite_ok}
EOF

# Only updated on a fully clean run — this file's own timestamp going
# stale *is* the failure signal /api/health and the data quality panel
# read (spec 6.6: "warns when the last successful backup is older than
# 48 hours"), rather than trying to push an alert the moment something
# breaks (ADR 0012: deliberately deferred).
#
# Deliberately still means *local* layers 1+2 only, and is written before
# the offsite result is considered: a NAS that is rebooting or asleep
# must not make the dashboard claim there is no backup at all, when the
# local one is fine. The offsite leg gets its own independent marker
# below so that neither can mask the other (ADR 0015).
local_run_ok=false
if [ "$backup_ok" = true ] && [ "$integrity_ok" = true ] && [ "$content_ok" = true ] && [ "$export_ok" = true ]; then
  echo "$timestamp" > "$BACKUP_DIR/last_success"
  local_run_ok=true
fi

if [ "$offsite_ok" = true ]; then
  echo "$timestamp" > "$BACKUP_DIR/last_offsite_success"
fi

# Guarded on a fully successful local run, mirroring the NAS retention
# guard below — unlike the NAS side, these two lines used to run
# unconditionally on every invocation, success or not. A failed run
# (export_ok=false, or the pre-flight/content check above rejecting an
# empty source) would still reach here under the old code and prune
# perfectly good backups purely by mtime, with nothing to show for it:
# fifteen consecutive failed nights would delete the last good local
# backup. `|| true` for the same reason the NAS retention lines have it —
# a transient permission error here must not abort the script after the
# markers above were already written.
if [ "$local_run_ok" = true ]; then
  find "$BACKUP_DIR" -maxdepth 1 -name 'cairn-*.db' -mtime "+$RETENTION_DAYS" -delete || true
  find "$BACKUP_DIR" -maxdepth 1 -name 'cairn-export-*.zip' -mtime "+$RETENTION_DAYS" -delete || true
fi

# Offsite retention. Note what is *not* here: the logical exports are
# never pruned. They are the smallest files and the only layer that
# survives a schema change, an app rewrite or a corrupt .db — exactly the
# failure modes long retention exists for. Keeping all of them costs
# roughly nothing.
#
# First-of-month .db snapshots are held back from the daily sweep and
# aged out separately, which gives five years of monthly reach for two
# find lines instead of a full grandfather-father-son implementation. If
# the Pi happened to be down on the 1st, that month simply has no
# long-term keeper — acceptable, since the 180-day window covers every
# recent month regardless.
if [ "$offsite_ok" = true ]; then
  timeout 300 find "$NAS_DB_DIR" -maxdepth 1 -name 'cairn-????-??-??.db' \
    ! -name 'cairn-????-??-01.db' -mtime "+$NAS_DAILY_DAYS" -delete || true
  timeout 300 find "$NAS_DB_DIR" -maxdepth 1 -name 'cairn-????-??-01.db' \
    -mtime "+$NAS_MONTHLY_DAYS" -delete || true
  timeout 300 find "$NAS_PRE_DIR" -maxdepth 1 -name 'pre-migration-*.db' \
    -mtime "+$NAS_PRE_DAYS" -delete || true
  # Defensive: nothing here should create these any more, but anyone who
  # opens a copy on the share to check it will strand a pair, and they
  # would otherwise sit next to the restore candidates forever — the
  # retention patterns above deliberately do not match them.
  timeout 300 find "$NAS_DB_DIR" "$NAS_PRE_DIR" -maxdepth 1 \
    \( -name '*.db-wal' -o -name '*.db-shm' \) -delete || true
fi

if [ "$local_run_ok" = true ] && [ "$offsite_ok" = true ]; then
  echo "backup ok: $timestamp"
else
  echo "backup FAILED: backup_ok=$backup_ok integrity_ok=$integrity_ok content_ok=$content_ok export_ok=$export_ok offsite_ok=$offsite_ok" >&2
  exit 1
fi
