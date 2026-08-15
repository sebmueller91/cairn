#!/bin/bash
# Build natively on the Mac (same arch as the Pi, no QEMU — ADR 0007), push
# to the Pi's local registry, take a pre-migration backup if data already
# exists (ADR 0008), then pull + restart on the Pi.
set -euo pipefail

PI_HOST="sebastian@raspberrypi5"
PI_KEY="$HOME/.ssh/cairn_pi"
REGISTRY="raspberrypi5:5000"
TAG="${1:-latest}"

cd "$(dirname "$0")/.."

echo "==> Building cairn-api:$TAG"
docker build -t "$REGISTRY/cairn-api:$TAG" ./backend

echo "==> Pushing to $REGISTRY"
docker push "$REGISTRY/cairn-api:$TAG"

echo "==> Syncing compose file to the Pi"
scp -i "$PI_KEY" deploy/docker-compose.yml "$PI_HOST:/srv/cairn/docker-compose.yml"

echo "==> Pre-migration backup + deploy on the Pi"
# shellcheck disable=SC2087
ssh -i "$PI_KEY" "$PI_HOST" REGISTRY="$REGISTRY" TAG="$TAG" bash -s <<'EOF'
set -euo pipefail

if [ -f /srv/cairn/data/cairn.db ]; then
  ts=$(date +%Y%m%d-%H%M%S)
  sqlite3 /srv/cairn/data/cairn.db ".backup '/srv/cairn/backups/pre-migration-$ts.db'"
  sqlite3 "/srv/cairn/backups/pre-migration-$ts.db" "PRAGMA integrity_check;"
  echo "pre-migration backup: pre-migration-$ts.db"
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
# here, unlike the Mac side which must reach it as raspberrypi5:5000.
export REGISTRY=localhost:5000 TAG
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d
EOF

echo "==> Waiting for health check"
sleep 2
curl -sf "http://raspberrypi5:8000/api/health"
echo
echo "==> Deployed cairn-api:$TAG"
