#!/bin/bash
# Install the bundle built by export-dev-secrets.sh onto a fresh development
# Mac, from inside a fresh clone of this repository.
#
# Everything here is idempotent and refuses to clobber: if a file already
# exists with different content the script stops and names it, rather than
# overwriting an SSH key or a CA you may still need. Re-running after a
# partial failure is safe.
#
# Run:  ./scripts/import-dev-secrets.sh /Volumes/cairn-dev-secrets
set -euo pipefail

cd "$(dirname "$0")/.."

SRC="${1:-/Volumes/cairn-dev-secrets}"
[ -d "$SRC" ] || {
  echo "no such directory: $SRC" >&2
  echo "Pass the plain bundle folder, or double-click the .dmg and pass the mounted volume." >&2
  exit 1
}
[ -f "$SRC/MANIFEST.txt" ] || { echo "$SRC does not look like a cairn secret bundle" >&2; exit 1; }

# place <source> <destination> <mode>
place() {
  local src="$1" dst="$2" mode="$3"
  [ -f "$src" ] || { echo "missing from bundle: ${src#$SRC/}" >&2; exit 1; }
  if [ -f "$dst" ] && ! cmp -s "$src" "$dst"; then
    echo "refusing to overwrite differing file: $dst" >&2
    echo "  inspect it, move it aside, and re-run" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  # Set explicitly: modes do not survive the trip through the disk image,
  # and ssh silently ignores a private key that is group-readable.
  chmod "$mode" "$dst"
  echo "    $dst"
}

PI_NAME=""
# shellcheck disable=SC1091
. "$SRC/repo/deploy/deploy.env"
: "${PI_NAME:?the bundle deploy.env has no PI_NAME}"

echo "==> SSH key for the Pi"
place "$SRC/ssh/cairn_pi"     "$HOME/.ssh/cairn_pi"     600
place "$SRC/ssh/cairn_pi.pub" "$HOME/.ssh/cairn_pi.pub" 644

if [ -s "$SRC/ssh/known_hosts" ]; then
  touch "$HOME/.ssh/known_hosts"; chmod 600 "$HOME/.ssh/known_hosts"
  while IFS= read -r line; do
    grep -qxF "$line" "$HOME/.ssh/known_hosts" || echo "$line" >> "$HOME/.ssh/known_hosts"
  done < "$SRC/ssh/known_hosts"
  echo "    Pi host key -> ~/.ssh/known_hosts"
fi

echo "==> mkcert CA"
command -v mkcert >/dev/null || { echo "mkcert not installed — brew install mkcert nss" >&2; exit 1; }
CAROOT=$(mkcert -CAROOT)
mkdir -p "$CAROOT"
place "$SRC/mkcert/rootCA.pem"     "$CAROOT/rootCA.pem"     644
place "$SRC/mkcert/rootCA-key.pem" "$CAROOT/rootCA-key.pem" 400
# The same CA, not a new one: every phone, tablet and browser in the house
# already trusts this root, and regenerating it would mean re-trusting it on
# all of them. The key comes along so this Mac can also reissue the leaf
# certificate if the Pi's LAN address ever changes (ADR 0014).
echo "==> Trusting the CA in this Mac's stores (may prompt for your password)"
mkcert -install

echo "==> Repository-local files"
place "$SRC/repo/deploy/deploy.env"              "deploy/deploy.env"               644
place "$SRC/repo/deploy/tls/$PI_NAME.pem"        "deploy/tls/$PI_NAME.pem"         644
place "$SRC/repo/deploy/tls/$PI_NAME-key.pem"    "deploy/tls/$PI_NAME-key.pem"     600
place "$SRC/repo/docs/etf-compositions.json"     "docs/etf-compositions.json"      644

echo "==> Docker insecure registry"
# The Pi's registry:2 has no TLS. On the Pi itself Docker trusts it because
# localhost:5000 falls inside 127.0.0.0/8, but deploy.sh pushes to it from
# here as $PI_NAME:5000, which Docker refuses over plain HTTP unless it is
# listed. Without this the deploy fails at the push step with an http/https
# error that reads like a network problem.
DAEMON="$HOME/.docker/daemon.json"
mkdir -p "$(dirname "$DAEMON")"
[ -f "$DAEMON" ] || echo '{}' > "$DAEMON"
if jq -e --arg r "$PI_NAME:5000" '."insecure-registries" // [] | index($r)' "$DAEMON" >/dev/null; then
  echo "    already present: $PI_NAME:5000"
else
  cp "$DAEMON" "$DAEMON.bak-$(date +%Y%m%d-%H%M%S)"
  tmp=$(mktemp)
  jq --arg r "$PI_NAME:5000" '."insecure-registries" = ((."insecure-registries" // []) + [$r] | unique)' \
    "$DAEMON" > "$tmp" && mv "$tmp" "$DAEMON"
  echo "    added $PI_NAME:5000 — restart Docker Desktop for it to take effect"
  RESTART_DOCKER=1
fi

echo "==> MCP server"
# Run through the CLI rather than printing the token for someone to paste:
# a token echoed into a terminal is a token in the scrollback, and if an
# agent is driving this script, in its transcript too.
if [ -d mcp_server/.venv ]; then
  echo "    venv exists, skipping create"
else
  # The mcp package needs Python >= 3.10; macOS's /usr/bin/python3 is 3.9.
  command -v python3.12 >/dev/null || { echo "python3.12 not installed — brew install python@3.12" >&2; exit 1; }
  python3.12 -m venv mcp_server/.venv
  mcp_server/.venv/bin/pip install -q -r mcp_server/requirements.txt
  echo "    created mcp_server/.venv"
fi
if command -v claude >/dev/null; then
  # shellcheck disable=SC1091
  set -a; . "$SRC/mcp/cairn.env"; set +a
  claude mcp remove cairn >/dev/null 2>&1 || true
  claude mcp add cairn \
    --env "CAIRN_API_URL=$CAIRN_API_URL" \
    --env "CAIRN_API_TOKEN=$CAIRN_API_TOKEN" \
    -- "$PWD/mcp_server/.venv/bin/python" "$PWD/mcp_server/server.py" >/dev/null
  unset CAIRN_API_TOKEN
  echo "    registered as 'cairn' for this project"
else
  echo "    claude CLI not on PATH — register it later, token is in $SRC/mcp/cairn.env"
fi

echo
echo "==> Secrets installed."
[ -n "${RESTART_DOCKER:-}" ] && echo "    Restart Docker Desktop before deploying."
echo "    Next: the toolchain and verification steps in docs/dev-machine-setup.md."
echo
# Phrased for whichever form arrived: an encrypted image mounted under
# /Volumes, or a plain folder carried over by hand. The plain one holds the
# keys in the clear, so saying "delete it" vaguely is not good enough.
case "$SRC" in
  /Volumes/*) echo "    Then eject the volume and delete the .dmg from both machines." ;;
  *)          echo "    Then delete the bundle from both machines and any stick it travelled on:"
              echo "        rm -rf \"$SRC\"" ;;
esac
