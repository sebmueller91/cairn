# Disaster recovery

Spec 6.6: *"Restore. Must be documented and actually rehearsed once."*
This is that document. The premise that makes it short: **the application
is fully reproducible from this repository** — only the data and the
secrets are not, and both have a defined home outside the Pi.

## What exists, where

| Thing | Location | Committed? |
|---|---|---|
| Application (API, frontend, Caddyfile, compose, scripts) | this repository | yes |
| SQLite database | `/srv/cairn/data/cairn.db` on the Pi | never |
| Nightly DB snapshots (`.backup` + integrity check) | `/srv/cairn/backups/cairn-YYYY-MM-DD.db` | never |
| Nightly logical exports (CSV+JSON ZIP) | `/srv/cairn/backups/cairn-export-YYYY-MM-DD.zip` | never |
| API token(s) | `/srv/cairn/config/.env` **and your password manager** | never |
| mkcert CA + leaf cert | dev Mac (`mkcert -CAROOT`) and `deploy/tls/` (gitignored) | never |
| Backup cron | `crontab -l` on the Pi: `0 3 * * * /srv/cairn/backup.sh >> /srv/cairn/backups/cron.log 2>&1` | documented here |

> **Known gap:** backup layer 3 (offsite 3-2-1 to NAS + encrypted cloud)
> is **not set up yet** — deliberately deferred until NAS/cloud details
> exist. Until then, a dead Pi *SD card* is recoverable from
> `/srv/cairn/backups` only if that directory lives on separate storage
> (SSD); a fully dead/stolen Pi loses everything since the last time you
> copied a backup off the device. Copy one off manually now and then, or
> close this gap.

## Scenario A — bad migration or wrecked ledger (Pi still alive)

1. Stop the stack: `cd /srv/cairn && docker compose down`
2. Pick a known-good snapshot from `/srv/cairn/backups/` (pre-migration
   snapshots from deploys are also there: `pre-migration-*.db`).
3. Verify it before trusting it:
   `sqlite3 <backup>.db "PRAGMA integrity_check;"` → must print `ok`.
4. Replace the live file:
   `cp <backup>.db /srv/cairn/data/cairn.db`
   (remove any stale `cairn.db-wal`/`cairn.db-shm` alongside it).
5. `docker compose up -d` — the entrypoint runs `alembic upgrade head`
   against the restored file.
6. Check `https://raspberrypi5/api/health`, then rebuild derived data:
   `POST /api/admin/rebuild-snapshots` and `POST /api/prices/refresh`
   (both are caches; the ledger is the truth — ADR 0003).

If even the newest `.db` snapshot is bad, the logical export ZIP is the
way back in: it contains every write primitive (accounts, instruments,
transactions, anchors, loans, index points, compositions, target
allocation) as CSV/JSON. Transactions carry their original
`external_id`s, so re-importing through `POST /api/transactions/bulk`
is idempotent and safe to re-run. There is no automated import tool —
this is the deliberate "survives the application itself" layer, expected
to be driven by a human or agent against whatever system exists then.

## Scenario B — the Pi is dead

Roughly half an hour, as spec 6.6 estimates:

1. Fresh Ubuntu 24.04 on a new card/board, hostname `raspberrypi5`,
   install Docker + compose plugin, create `sebastian` with your SSH key.
2. Recreate the directory skeleton:
   `sudo mkdir -p /srv/cairn/{data,config,backups,tls,frontend-dist,registry}`
   and `chown` to `sebastian`.
3. Write `/srv/cairn/config/.env` with `API_TOKEN=` from your
   **password manager** (this is exactly why it lives there and not only
   on the Pi).
4. Restore the newest surviving backup to `/srv/cairn/data/cairn.db`
   (integrity-check it first, as above).
5. Start the local registry the deploy pipeline pushes to:
   `docker run -d --restart=always -p 5000:5000 --name registry -v /srv/cairn/registry:/var/lib/registry registry:2`
6. From the dev Mac, in this repo: `./scripts/deploy.sh` — builds and
   ships the API image, frontend, Caddyfile, TLS cert, compose file, and
   `backup.sh`.
7. Reinstall the cron line (table above).
8. Rebuild caches (`rebuild-snapshots`, `prices/refresh`) and check
   the dashboard.

The mkcert CA lives on the dev Mac, so certificates survive a Pi death
untouched. If the **dev Mac** dies instead: a new `mkcert -install` CA
means re-trusting the new root cert on every device (ADR 0014) — annoying
but not data loss.

## Rehearsal log

- **2026-08-15** — Scenario A mechanics rehearsed from the dev Mac:
  pulled that night's `cairn-2026-08-15.db` off the Pi, verified
  `PRAGMA integrity_check` → `ok`, booted the API locally against the
  restored file (`DATABASE_PATH` override), confirmed `/api/health` ok
  and authenticated reads served. Not yet rehearsed: a full Scenario B
  bare-metal rebuild (needs spare hardware), and any layer-3 offsite
  restore (layer 3 doesn't exist yet).
