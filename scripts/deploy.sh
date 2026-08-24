#!/bin/bash
# Build natively on the Mac (same arch as the Pi, no QEMU — ADR 0007), push
# to the Pi's local registry, take a pre-migration backup if data already
# exists (ADR 0008), then pull + restart on the Pi. Since phase 6 (ADR
# 0014) this also builds the frontend and syncs it, the Caddyfile, and the
# mkcert TLS cert — Caddy is the only published entry point now.
#
# Ordering is deliberate and load-bearing: everything that only touches
# the Mac or the Pi's local registry happens first; every prerequisite is
# validated before anything on the Pi is mutated; and the frontend is the
# very last thing synced, only after the new API has been confirmed
# healthy. A frontend built against a newer API must never be live before
# that API is — otherwise it's talking to the old API, then briefly to no
# API at all while the container restarts.
set -euo pipefail

TAG="${1:-latest}"

cd "$(dirname "$0")/.."

# Where this instance lives. Not in the repository: a public clone should
# not carry someone's LAN topology around. deploy/deploy.env.example shows
# the shape; environment variables still win over the file.
if [ -f deploy/deploy.env ]; then
  # shellcheck disable=SC1091
  . ./deploy/deploy.env
fi

PI_USER="${PI_USER:-}"
PI_NAME="${PI_NAME:-}"
PI_FQDN="${PI_FQDN:-}"
PI_LAN_IP="${PI_LAN_IP:-}"
PI_KEY="${PI_KEY:-$HOME/.ssh/cairn_pi}"
PI_HOST="$PI_USER@$PI_NAME"
REGISTRY="$PI_NAME:5000"

echo "==> Validating prerequisites"
# All local and read-only — nothing on the Pi has been touched yet, so
# failing here costs only time. Found live: deploy/tls/*.pem is
# gitignored (never committed, per AGENTS.md "secrets live outside the
# repository"), so on a fresh clone the scp of the cert used to fail —
# but only *after* `rsync --delete` had already replaced the frontend,
# leaving no rollback path short of a manual restore. Checking every
# input the rest of this script depends on, before it mutates anything,
# turns that into a clean, harmless exit instead.
for v in PI_USER PI_NAME PI_FQDN PI_LAN_IP; do
  [ -n "${!v}" ] || {
    echo "$v is not set — copy deploy/deploy.env.example to deploy/deploy.env and fill it in" >&2
    exit 1
  }
done
[ -f "$PI_KEY" ] || { echo "missing SSH key: $PI_KEY" >&2; exit 1; }
for f in "deploy/tls/$PI_NAME.pem" "deploy/tls/$PI_NAME-key.pem"; do
  [ -f "$f" ] || {
    echo "missing TLS material: $f (mkcert output — see docs/adr/0014, never committed)" >&2
    exit 1
  }
done
[ -f deploy/Caddyfile.template ] || { echo "missing deploy/Caddyfile.template" >&2; exit 1; }
[ -f deploy/docker-compose.yml ] || { echo "missing deploy/docker-compose.yml" >&2; exit 1; }
command -v mkcert >/dev/null || {
  echo "mkcert not found on PATH (needed below for the health check's CA root)" >&2
  exit 1
}

echo "==> Building cairn-api:$TAG"
docker build -t "$REGISTRY/cairn-api:$TAG" ./backend

echo "==> Pushing to $REGISTRY"
docker push "$REGISTRY/cairn-api:$TAG"

# Built now but deliberately not synced yet — see the ordering note above.
echo "==> Building frontend"
npm --prefix frontend ci
npm --prefix frontend run build
[ -d frontend/dist ] || { echo "frontend build did not produce frontend/dist" >&2; exit 1; }

echo "==> Ensuring remote directories exist"
ssh -i "$PI_KEY" "$PI_HOST" 'mkdir -p /srv/cairn/frontend-dist /srv/cairn/tls'

echo "==> Syncing Caddyfile, TLS cert, compose file, and backup script to the Pi"
# Rendered here rather than committed: the repository holds the shape,
# deploy/deploy.env holds this instance's names. A leftover @MARKER@ would
# make Caddy fail to parse on the Pi, so check before shipping it.
CADDYFILE=$(mktemp)
trap 'rm -f "$CADDYFILE"' EXIT
sed -e "s|@PI_NAME@|$PI_NAME|g" \
    -e "s|@PI_FQDN@|$PI_FQDN|g" \
    -e "s|@PI_LAN_IP@|$PI_LAN_IP|g" \
    deploy/Caddyfile.template > "$CADDYFILE"
# mktemp is 0600; the committed file was world-readable and Caddy reads it
# through a read-only bind mount. Keep the mode the Pi had before.
chmod 644 "$CADDYFILE"
! grep -q '@PI_[A-Z_]*@' "$CADDYFILE" || {
  echo "unsubstituted marker left in the rendered Caddyfile:" >&2
  grep -n '@PI_[A-Z_]*@' "$CADDYFILE" >&2
  exit 1
}
scp -i "$PI_KEY" "$CADDYFILE" "$PI_HOST:/srv/cairn/Caddyfile"
scp -i "$PI_KEY" "deploy/tls/$PI_NAME.pem" "deploy/tls/$PI_NAME-key.pem" "$PI_HOST:/srv/cairn/tls/"
scp -i "$PI_KEY" deploy/docker-compose.yml "$PI_HOST:/srv/cairn/docker-compose.yml"
scp -i "$PI_KEY" scripts/backup.sh "$PI_HOST:/srv/cairn/backup.sh"
ssh -i "$PI_KEY" "$PI_HOST" 'chmod +x /srv/cairn/backup.sh'

echo "==> Pre-migration backup + deploy on the Pi"
# shellcheck disable=SC2087
ssh -i "$PI_KEY" "$PI_HOST" REGISTRY="$REGISTRY" TAG="$TAG" bash -s <<'EOF'
set -euo pipefail

if [ -f /srv/cairn/data/cairn.db ]; then
  ts=$(date +%Y%m%d-%H%M%S)
  sqlite3 /srv/cairn/data/cairn.db ".backup '/srv/cairn/backups/pre-migration-$ts.db'"
  # sqlite3 exits 0 whether the answer is "ok" or a list of corruption
  # reports, so `set -e` alone can't catch a bad backup — capture and
  # assert, matching scripts/backup.sh's pattern. This is the one check
  # standing between a bad migration and data loss; ADR 0008's entire
  # rollback story rests on this snapshot being good, so a result other
  # than "ok" must abort the deploy here, before Alembic ever runs.
  result=$(sqlite3 "/srv/cairn/backups/pre-migration-$ts.db" "PRAGMA integrity_check;")
  if [ "$result" != "ok" ]; then
    echo "pre-migration backup FAILED integrity check: $result" >&2
    exit 1
  fi
  echo "pre-migration backup ok: pre-migration-$ts.db"
else
  echo "no existing db — first deploy, skipping pre-migration backup"
fi

cd /srv/cairn
set -a
# shellcheck disable=SC1091
source /srv/cairn/config/.env
set +a
# Pulled locally on the Pi: address the registry as localhost, which Docker
# trusts as insecure by default (127.0.0.0/8) — no daemon.json change needed
# here, unlike the Mac side which must reach it as $PI_NAME:5000.
export REGISTRY=localhost:5000 TAG
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d

# `up -d` only recreates a container whose *spec* changed. The caddy
# service's spec never changes just because the bind-mounted Caddyfile or
# TLS cert content did, so a plain `up -d` can report success while the
# running Caddy keeps its old in-memory config and already-loaded
# certificate — regenerating the cert after an IP change would otherwise
# look like a successful deploy and change nothing. Caddy doesn't watch
# its config file, so it needs an explicit kick. A full restart (rather
# than an admin-API `caddy reload`) is used deliberately: the Caddyfile
# turns the admin API off, and enabling it just to support a graceful
# reload is a bigger change than this bug calls for. A restart is brief
# (comparable to the api container's own restart above) and always picks
# up whatever is currently on disk.
docker compose -f docker-compose.yml restart caddy
EOF

echo "==> Waiting for health check"
# uvicorn boot plus Alembic migrations on a Pi 5 can reasonably take
# longer than a flat `sleep 2` — that made a successful deploy look
# broken (or let a genuinely broken one slip through, if the sleep
# happened to be enough that run). Poll with a real timeout instead: 3s
# between attempts, up to 90s total, which is generous headroom for this
# hardware without hanging the script indefinitely on a truly failed
# deploy.
health_timeout=90
health_interval=3
SECONDS=0
until curl -sf --cacert "$(mkcert -CAROOT)/rootCA.pem" "https://$PI_NAME/api/health" >/dev/null; do
  if [ "$SECONDS" -ge "$health_timeout" ]; then
    echo "health check did not succeed within ${health_timeout}s" >&2
    exit 1
  fi
  sleep "$health_interval"
done
curl -sf --cacert "$(mkcert -CAROOT)/rootCA.pem" "https://$PI_NAME/api/health"
echo

# Last step, and only reached once the API above answered healthy on
# $TAG (migrations applied) — see the ordering note at the top of this
# file. Caddy serves this straight off disk with no restart needed.
echo "==> Syncing frontend to the Pi"
rsync -az --delete -e "ssh -i $PI_KEY" frontend/dist/ "$PI_HOST:/srv/cairn/frontend-dist/"

echo "==> Deployed cairn-api:$TAG"
