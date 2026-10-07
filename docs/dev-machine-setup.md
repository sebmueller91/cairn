# Setting up a second development Mac

Everything an agent (or you) needs to go from a blank Apple Silicon Mac to
"tests green, `./scripts/deploy.sh` works". The application is reproducible
from this repository; what is not is the handful of secrets and site-local
files listed in `docs/disaster-recovery.md`. Those travel as a bundle made by
`scripts/export-dev-secrets.sh` on the existing Mac and installed by
`scripts/import-dev-secrets.sh` on the new one.

Must be Apple Silicon: the deploy builds the `arm64` image natively (ADR 0007).
Must be on the home LAN (or VPN) for anything that touches the Pi.

## 1. Toolchain

```bash
xcode-select --install          # git, if not already there
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12 node mkcert nss jq gh
brew install --cask docker      # then open Docker Desktop once and finish its setup
```

`/usr/bin/python3` is 3.9 — always use `python3.12` explicitly. CI runs Node 20;
any newer Node works locally.

## 2. GitHub access (interactive — the human runs this)

```bash
gh auth login                   # GitHub.com → HTTPS → login with browser
gh auth setup-git
git config --global user.name  "<your name>"
git config --global user.email "<your email>"
```

## 3. Clone and install the secrets

```bash
mkdir -p ~/repos && git clone https://github.com/sebmueller91/cairn.git ~/repos/cairn
cd ~/repos/cairn
# Only if the clone predates the scripts being committed:
[ -f scripts/import-dev-secrets.sh ] || cp <bundle>/tools/import-dev-secrets.sh scripts/
./scripts/import-dev-secrets.sh <bundle>      # folder path, or /Volumes/cairn-dev-secrets for the .dmg
```

It installs the Pi SSH key and host key, the mkcert CA (and trusts it —
prompts for the macOS password), `deploy/deploy.env`, the TLS leaf cert,
`docs/etf-compositions.json`, the Docker insecure-registry entry, and
registers the `cairn` MCP server with Claude Code. **Restart Docker Desktop**
if it says so.

## 4. Project dependencies

```bash
cd ~/repos/cairn/backend  && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cd ~/repos/cairn/frontend && npm ci
```

## 5. Verify

```bash
cd ~/repos/cairn
(cd backend && .venv/bin/python -m pytest -q)                  # all green
npm --prefix frontend run lint && npm --prefix frontend test

. deploy/deploy.env
ssh -i ~/.ssh/cairn_pi -o BatchMode=yes "$PI_USER@$PI_NAME" 'docker ps --format "{{.Names}}"'
curl -sf --cacert "$(mkcert -CAROOT)/rootCA.pem" "https://$PI_NAME/api/health"
claude mcp get cairn            # should say Connected
```

If the ssh step fails with a host-key prompt, run it once interactively and
accept; if `curl` fails on the certificate, `mkcert -install` did not run.

## 6. Deploy

```bash
./scripts/deploy.sh
```

A first `docker push` failing with an "http: server gave HTTP response to
HTTPS client" error means Docker Desktop has not been restarted since the
insecure-registry entry was added.

## 7. Clean up

Delete the bundle (and the `.dmg`, if that was the form) from both Macs and
anything it travelled on.

Not carried over, on purpose: the Pi's `/srv/cairn/config/.env` and the NAS
credentials stay on the Pi and in the password manager — a dev Mac never reads
them. The bundle carries only the bearer token the MCP server uses.
`backend/cairn.db` is a scratch database — make a fresh one per the README.
