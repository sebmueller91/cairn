#!/bin/bash
# Exercises scripts/backup.sh against scratch directories, with the few
# things that need a real Pi (the API, the CIFS mount) stubbed on PATH.
#
# ADR 0009 accepted that the backup job "lives outside the app's own code
# and test suite — mitigated by keeping it a short, reviewed shell
# script". Once it grew a third leg with its own failure modes, review
# alone stopped being enough: the properties below are the ones whose
# quiet breakage would look exactly like a working backup.
#
# Run from anywhere: ./scripts/test-backup.sh
set -uo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT

pass=0
fail=0
check() { # check <description> <condition-as-command...>
  local desc="$1"; shift
  if "$@"; then
    printf '  ok   %s\n' "$desc"; pass=$((pass + 1))
  else
    printf '  FAIL %s\n' "$desc"; fail=$((fail + 1))
  fi
}

# --- stubs ----------------------------------------------------------------
# `timeout` and `findmnt` are Linux-only; `curl` would need a live API.
mkdir -p "$ROOT/bin"
cat > "$ROOT/bin/timeout" <<'STUB'
#!/bin/bash
shift          # drop the duration; the point here is behaviour, not timing
exec "$@"
STUB
cat > "$ROOT/bin/findmnt" <<'STUB'
#!/bin/bash
# Claims a CIFS filesystem only when the harness says so, which is how
# the "unmounted target" case is simulated without root or a real mount.
[ "${FAKE_CIFS:-0}" = "1" ]
STUB
cat > "$ROOT/bin/curl" <<'STUB'
#!/bin/bash
# Stands in for GET /api/export/full: writes a real (tiny) zip to -o.
out=""
while [ $# -gt 0 ]; do
  [ "$1" = "-o" ] && { out="$2"; shift 2; continue; }
  shift
done
[ "${FAKE_EXPORT_FAILS:-0}" = "1" ] && exit 22
python3 -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('accounts.csv','id,name\n'); z.close()" "$out"
STUB
chmod +x "$ROOT/bin"/*
export PATH="$ROOT/bin:$PATH"

# --- fixture --------------------------------------------------------------
setup() {
  rm -rf "$ROOT/data" "$ROOT/backups" "$ROOT/nas" "$ROOT/config"
  mkdir -p "$ROOT/data" "$ROOT/backups" "$ROOT/nas" "$ROOT/config"
  # Invented numbers only (AGENTS.md) — this is a schema smoke fixture,
  # not a ledger.
  sqlite3 "$ROOT/data/cairn.db" \
    "CREATE TABLE txn (id INTEGER PRIMARY KEY, amount TEXT); \
     INSERT INTO txn (amount) VALUES ('123.45');"
  echo 'API_TOKEN=test-token-not-a-real-one' > "$ROOT/config/.env"
}

run_backup() {
  DATA_DIR="$ROOT/data" BACKUP_DIR="$ROOT/backups" ENV_FILE="$ROOT/config/.env" \
  NAS_MOUNT="$ROOT/nas" EXPORT_URL="http://stub/export" \
    bash "$REPO/scripts/backup.sh" >"$ROOT/out.log" 2>"$ROOT/err.log"
  echo $?
}

TODAY=$(date +%F)

echo
echo "1. Happy path: the NAS is mounted and reachable"
setup
FAKE_CIFS=1
export FAKE_CIFS
rc=$(run_backup)
check "exits 0"                          test "$rc" = "0"
check "db snapshot reached the NAS"      test -f "$ROOT/nas/cairn/db/cairn-$TODAY.db"
check "export reached the NAS"           test -f "$ROOT/nas/cairn/exports/cairn-export-$TODAY.zip"
check "local last_success written"       test -f "$ROOT/backups/last_success"
check "offsite marker written"           test -f "$ROOT/backups/last_offsite_success"
check "latest_run.json reports offsite"  grep -q '"offsite_ok": true' "$ROOT/backups/latest_run.json"
check "NAS copy is a valid database" \
  bash -c "[ \"\$(sqlite3 'file:$ROOT/nas/cairn/db/cairn-$TODAY.db?immutable=1' 'PRAGMA integrity_check;')\" = ok ]"
# A -wal/-shm pair beside a restore candidate is a hazard, and on CIFS
# they are not cleaned up on close the way they are locally.
check "no stray wal/shm left on the NAS" \
  bash -c "[ -z \"\$(find '$ROOT/nas' -name '*.db-wal' -o -name '*.db-shm')\" ]"

echo
echo "2. NAS unreachable: the local backup must still count as a success"
setup
FAKE_CIFS=0
export FAKE_CIFS
rc=$(run_backup)
check "exits non-zero (cron sees a failure)" test "$rc" != "0"
check "local last_success STILL written"     test -f "$ROOT/backups/last_success"
check "offsite marker NOT written"           test ! -f "$ROOT/backups/last_offsite_success"
check "latest_run.json reports offsite false" grep -q '"offsite_ok": false' "$ROOT/backups/latest_run.json"
check "local db snapshot still taken"        test -f "$ROOT/backups/cairn-$TODAY.db"
check "nothing written into the unmounted dir" test ! -d "$ROOT/nas/cairn"
check "refusal is explained on stderr"       grep -q "refusing to write to local disk" "$ROOT/err.log"

echo
echo "3. No --delete: a deletion on the Pi must not propagate to the NAS"
setup
FAKE_CIFS=1
export FAKE_CIFS
run_backup >/dev/null
# An older copy that exists on both sides, then vanishes from the Pi —
# the ransomware / rm -rf / script-bug shape.
cp "$ROOT/backups/cairn-$TODAY.db" "$ROOT/backups/cairn-2026-01-02.db"
cp "$ROOT/backups/cairn-$TODAY.db" "$ROOT/nas/cairn/db/cairn-2026-01-02.db"
rm "$ROOT/backups/cairn-2026-01-02.db"
run_backup >/dev/null
check "NAS copy survives deletion on the Pi" test -f "$ROOT/nas/cairn/db/cairn-2026-01-02.db"

echo
echo "4. Export fails: offsite must not claim success on a half-finished run"
setup
FAKE_CIFS=1 FAKE_EXPORT_FAILS=1
export FAKE_CIFS FAKE_EXPORT_FAILS
rc=$(run_backup)
unset FAKE_EXPORT_FAILS
check "exits non-zero"                    test "$rc" != "0"
check "local last_success NOT written"    test ! -f "$ROOT/backups/last_success"
check "offsite marker NOT written"        test ! -f "$ROOT/backups/last_offsite_success"

echo
echo "5. Retention: the sweep that stays silent for six months"
# The find lines below cannot delete anything for 180 days, so a mistake
# in them would surface only long after it mattered -- and the failure
# mode is deleting the wrong thing, permanently. Ages come from mtime,
# not the filename, so these are planted with explicit mtimes.
setup
FAKE_CIFS=1
export FAKE_CIFS
run_backup >/dev/null
plant() { # plant <path> <age-in-days>
  : > "$1"
  python3 -c "import os,sys,time; os.utime(sys.argv[1], (time.time()-float(sys.argv[2])*86400,)*2)" "$1" "$2"
}
plant "$ROOT/nas/cairn/db/cairn-2025-06-15.db"  440   # old daily
plant "$ROOT/nas/cairn/db/cairn-2025-06-01.db"  440   # old, but a 1st
plant "$ROOT/nas/cairn/db/cairn-2020-03-01.db"  2200  # a 1st, past 5 years
plant "$ROOT/nas/cairn/exports/cairn-export-2015-01-01.zip" 4000
plant "$ROOT/nas/cairn/pre-migration/pre-migration-20200101-000000.db" 400
plant "$ROOT/nas/cairn/pre-migration/pre-migration-20260101-000000.db" 30
run_backup >/dev/null
check "old daily snapshot swept"              test ! -f "$ROOT/nas/cairn/db/cairn-2025-06-15.db"
check "first-of-month KEPT past the daily window" test -f "$ROOT/nas/cairn/db/cairn-2025-06-01.db"
check "first-of-month swept past five years"  test ! -f "$ROOT/nas/cairn/db/cairn-2020-03-01.db"
check "today's snapshot untouched"            test -f "$ROOT/nas/cairn/db/cairn-$TODAY.db"
check "ancient export NEVER pruned"           test -f "$ROOT/nas/cairn/exports/cairn-export-2015-01-01.zip"
check "today's export untouched"              test -f "$ROOT/nas/cairn/exports/cairn-export-$TODAY.zip"
check "old pre-migration swept"               test ! -f "$ROOT/nas/cairn/pre-migration/pre-migration-20200101-000000.db"
check "recent pre-migration kept"             test -f "$ROOT/nas/cairn/pre-migration/pre-migration-20260101-000000.db"

echo
echo "6. Retention never runs on a failed offsite leg"
# Otherwise a night when the NAS was unreachable could still age files
# out of the only surviving copy.
setup
FAKE_CIFS=1
export FAKE_CIFS
run_backup >/dev/null
plant "$ROOT/nas/cairn/db/cairn-2025-06-15.db" 440
FAKE_CIFS=0
export FAKE_CIFS
run_backup >/dev/null
check "old file survives a run that could not reach the NAS" \
  test -f "$ROOT/nas/cairn/db/cairn-2025-06-15.db"

echo
if [ "$fail" -eq 0 ]; then
  echo "all $pass checks passed"
else
  echo "$fail of $((pass + fail)) checks FAILED"
  exit 1
fi
