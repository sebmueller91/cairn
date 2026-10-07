#!/bin/bash
# Gather everything a second development Mac needs that is not in git —
# the Pi's SSH key, the mkcert CA, deploy/deploy.env, the TLS leaf cert,
# the ETF compositions and the MCP token — into one bundle that
# scripts/import-dev-secrets.sh installs on the other side.
#
# Run from this (working) dev Mac:
#   ./scripts/export-dev-secrets.sh            # plain folder on ~/Desktop
#   ./scripts/export-dev-secrets.sh --dmg      # AES-256 disk image instead;
#                                              # hdiutil prompts for a password
#
# The plain folder holds the keys in the clear. Delete it once the other
# Mac is set up.
set -euo pipefail

cd "$(dirname "$0")/.."

DMG=""
[ "${1:-}" = "--dmg" ] && DMG=1

NAME=cairn-dev-secrets
OUT="$HOME/Desktop/$NAME"
[ -e "$OUT" ] && { echo "already exists: $OUT — move it aside first" >&2; exit 1; }

PI_NAME=""
# shellcheck disable=SC1091
. ./deploy/deploy.env
: "${PI_NAME:?deploy/deploy.env has no PI_NAME}"

umask 077
mkdir -p "$OUT"/{ssh,mkcert,mcp,tools,repo/deploy/tls,repo/docs}

# take <source> <bundle-relative destination>
take() {
  [ -f "$1" ] || { echo "missing on this Mac: $1" >&2; rm -rf "$OUT"; exit 1; }
  cp "$1" "$OUT/$2"
  echo "    $2"
}

echo "==> Collecting into $OUT"
take "$HOME/.ssh/cairn_pi"                  ssh/cairn_pi
take "$HOME/.ssh/cairn_pi.pub"              ssh/cairn_pi.pub
CAROOT=$(mkcert -CAROOT)
take "$CAROOT/rootCA.pem"                   mkcert/rootCA.pem
take "$CAROOT/rootCA-key.pem"               mkcert/rootCA-key.pem
take deploy/deploy.env                      repo/deploy/deploy.env
take "deploy/tls/$PI_NAME.pem"              "repo/deploy/tls/$PI_NAME.pem"
take "deploy/tls/$PI_NAME-key.pem"          "repo/deploy/tls/$PI_NAME-key.pem"
take docs/etf-compositions.json             repo/docs/etf-compositions.json
# The installer and the guide travel along too, so the bundle works even
# against a clone made before they were committed.
take scripts/import-dev-secrets.sh          tools/import-dev-secrets.sh
take docs/dev-machine-setup.md              tools/dev-machine-setup.md

# The Pi's host key, so the first ssh from the new Mac (usually inside
# deploy.sh, with nobody there to answer the fingerprint prompt) does not
# stop and ask.
for h in "$PI_NAME" "$PI_FQDN" "$PI_LAN_IP"; do
  ssh-keygen -F "$h" 2>/dev/null | grep -v '^#' || true
done > "$OUT/ssh/known_hosts"
[ -s "$OUT/ssh/known_hosts" ] || echo "    (no known_hosts entry for the Pi — first ssh will ask)"

# Lifted straight out of Claude Code's config rather than asked for, so the
# token never passes through a terminal or a transcript.
python3 - "$PWD" "$OUT/mcp/cairn.env" <<'PY'
import json, os, sys, shlex
repo, dst = sys.argv[1], sys.argv[2]
cfg = json.load(open(os.path.expanduser("~/.claude.json")))
env = cfg["projects"][repo]["mcpServers"]["cairn"]["env"]
with open(dst, "w") as f:
    for k in ("CAIRN_API_URL", "CAIRN_API_TOKEN"):
        f.write(f"{k}={shlex.quote(env[k])}\n")
PY
echo "    mcp/cairn.env"

{
  echo "cairn dev secret bundle — exported $(date '+%Y-%m-%d %H:%M') from $(scutil --get ComputerName 2>/dev/null || hostname)"
  echo "Install: ./scripts/import-dev-secrets.sh <this folder>"
  echo
  (cd "$OUT" && find . -type f ! -name MANIFEST.txt | sort | sed 's|^\./||')
} > "$OUT/MANIFEST.txt"

if [ -n "$DMG" ]; then
  echo "==> Encrypting (choose a password; you will type it again on the other Mac)"
  hdiutil create -quiet -encryption AES-256 -fs APFS \
    -volname "$NAME" -srcfolder "$OUT" "$OUT.dmg"
  rm -rf "$OUT"
  echo "==> Wrote $OUT.dmg"
else
  echo "==> Wrote $OUT (unencrypted — delete it once the other Mac is set up)"
fi
