# Disaster recovery

Spec 6.6: *"Restore. Must be documented and actually rehearsed once."*
This is that document. The premise that makes it short: **the application
is fully reproducible from this repository** — only the data and the
secrets are not, and both have a defined home outside the Pi.

## What exists, where

| Thing | Location | Committed? |
|---|---|---|
| Application (API, frontend, Caddyfile template, compose, scripts) | this repository | yes |
| SQLite database | `/srv/cairn/data/cairn.db` on the Pi | never |
| Nightly DB snapshots (`.backup` + integrity check) | `/srv/cairn/backups/cairn-YYYY-MM-DD.db` | never |
| Nightly logical exports (CSV+JSON ZIP) | `/srv/cairn/backups/cairn-export-YYYY-MM-DD.zip` | never |
| API token(s) | `/srv/cairn/config/.env` **and your password manager** | never |
| mkcert CA + leaf cert | dev Mac (`mkcert -CAROOT`) and `deploy/tls/` (gitignored) | never |
| Deploy target names (user, hostname, FQDN, LAN IP) | dev Mac, `deploy/deploy.env` (gitignored) | shape only, in `deploy/deploy.env.example` |
| Backup cron | `crontab -l` on the Pi: `0 3 * * * /srv/cairn/backup.sh >> /srv/cairn/backups/cron.log 2>&1` | documented here |
| Offsite copies on the NAS | `/srv/cairn/nas/cairn/{db,exports,pre-migration}/` (SMB share) | never |
| NAS mount units | `/etc/systemd/system/srv-cairn-nas.{mount,automount}` | templates in `deploy/systemd/` |
| NAS credentials | `/srv/cairn/config/nas.cred` **and your password manager** | never |

> **Layer 3 is complete, in two halves that are managed differently.**
> Pi → NAS runs nightly from `scripts/backup.sh` and is described here and in
> ADR 0015. **NAS → cloud runs weekly and is configured in DSM, not in this
> repository** — so 3-2-1 holds: the ledger exists on the Pi's SSD, on the
> NAS, and off-site.
>
> Because the cloud half lives outside this repo, nothing here can verify it.
> Three things about it are **unrecorded and worth pinning down**, since a
> backup nobody has checked is a guess: whether it is encrypted before it
> leaves the NAS (spec 6.6 is emphatic that it must be — the file is the
> complete financial picture, and the "only I can reach it" reasoning that
> justifies leaving the NAS copy in the clear does not extend to someone
> else's infrastructure), what its retention is, and whether a restore from
> it has ever been attempted. The weekly cadence also means up to seven days
> of the newest data exist only inside the house.

> **Not in any backup, by design:** `/srv/cairn/config/.env` (the API token)
> and `nas.cred`. Both live in your password manager instead — a backup that
> contained the credentials to reach it protects nothing.

### NAS-side configuration this repository cannot enforce

Three settings on the `cairn-backup` shared folder that the Pi cannot see and
`deploy/` cannot ship. All three were verified or set on 2026-08-22:

| Setting | Why it matters |
|---|---|
| **Recycle Bin: off** (or on a deletion schedule) | Measured: with it on, deleting a 200 MB file freed **no** quota. Retention would sweep files into `#recycle` and never reclaim anything, until the share filled and the offsite leg began failing — years later, silently. |
| **SMB transfer encryption: on** | The mount unit uses `seal`; without it the mount is refused. |
| **Btrfs snapshots: on** (daily, keep 30) | The only defence against the Pi mirroring a corrupt file or its credentials being abused — snapshots are not writable over SMB. |
| **Weekly cloud backup of the share** | The off-site leg of 3-2-1. Configured in DSM; see the note above for what about it is still unverified. |

### Offsite layer, in one paragraph

`scripts/backup.sh` mirrors each night's `.db` snapshot, logical export and
any deploy-time `pre-migration-*.db` to the NAS share, then re-runs
`PRAGMA integrity_check` and a ZIP check **against the copies on the NAS**
before recording success. It never passes `--delete`: the NAS side only ever
grows, so a bad night on the Pi cannot propagate. Retention there is 180 days
of daily snapshots, first-of-month snapshots for five years, deploy snapshots
for one year, and **logical exports are never deleted**. Local retention on
the Pi is unchanged at 14 days.

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
6. From the dev Mac, in this repo: make sure `deploy/deploy.env` exists
   (copy `deploy/deploy.env.example` and set `PI_USER`, `PI_NAME`,
   `PI_FQDN`, `PI_LAN_IP` — the same three names the mkcert leaf cert
   covers, or Caddy will serve a certificate that does not match), then
   `./scripts/deploy.sh` — builds and ships the API image, frontend,
   rendered Caddyfile, TLS cert, compose file, and `backup.sh`. The script
   refuses to touch the Pi if any of those variables is unset.
7. Reinstall the cron line (table above).
8. Re-establish the offsite leg, or the rebuilt Pi silently has no layer 3:
   `apt install cifs-utils`, write `/srv/cairn/config/nas.cred` (root-owned,
   `chmod 600`, `username=`/`password=` from your password manager), copy
   `deploy/systemd/srv-cairn-nas.{mount,automount}` to
   `/etc/systemd/system/` with the hostname and share name filled in (and
   the `uid=`/`gid=` matching whoever owns the backup crontab), then
   `systemctl daemon-reload && systemctl enable --now srv-cairn-nas.automount`.
   Confirm with a manual `/srv/cairn/backup.sh` run that `latest_run.json`
   reports `"offsite_ok": true`.
9. Rebuild caches (`rebuild-snapshots`, `prices/refresh`) and check
   the dashboard.

The mkcert CA lives on the dev Mac, so certificates survive a Pi death
untouched. If the **dev Mac** dies instead: a new `mkcert -install` CA
means re-trusting the new root cert on every device (ADR 0014) — annoying
but not data loss.

## Scenario C — the Pi and its SSD are both gone

The case that had no answer before ADR 0015. Identical to Scenario B, except
for where step 4's backup comes from: the NAS, not the Pi.

1. Mount the share anywhere convenient — the NAS is reachable from any
   machine on the LAN, and you do not need the new Pi to exist yet.
2. Take the newest `cairn/db/cairn-YYYY-MM-DD.db`, and **verify before
   trusting**: `sqlite3 <file> "PRAGMA integrity_check;"` → must print `ok`.
   If it does not, walk backwards through the daily copies; that is what the
   180-day window is for.
3. Continue from Scenario B step 1 with that file as the restore source.

If every `.db` copy is bad — the slow-corruption case, where the Pi has been
faithfully mirroring a damaged file for weeks — use `cairn/exports/`. Those
are never pruned, so there is a ZIP from before the damage. From there the
route back in is the logical import described at the end of Scenario A.

The NAS credentials are in your password manager; if the NAS shared folder
has Btrfs snapshots enabled, DSM's snapshot browser is a second source that
the Pi could never have written to, whatever went wrong on it.

## Rehearsal log

- **2026-08-22** — Scenario C rehearsed from the dev Mac, the day the
  offsite leg went live. Deliberately restored **not** that night's copy but
  an older retained one, since the point is that the retained copies are
  usable, not just the freshest: read it off `//<nas-hostname>/<share-name>` at
  `cairn/db/`, `PRAGMA integrity_check` → `ok`, booted the API against it
  locally (`DATABASE_PATH` override), confirmed `/api/health` reported the
  database reachable, that authenticated reads on accounts, transactions and
  positions all served, and that an unauthenticated read was still refused.
  The restored copy was deleted afterwards.
  Caveat on fidelity: the file was read through the Pi's mount of the share
  rather than by mounting the NAS independently, so what is proven is that
  the copy on the NAS restores — not the "Pi is gone, mount the NAS from
  somewhere else" step, which is a DSM credential exercise and untested.
  Still not rehearsed: a full Scenario B bare-metal rebuild (needs spare
  hardware), and any restore of the NAS → cloud layer, which does not exist.
- **2026-08-15** — Scenario A mechanics rehearsed from the dev Mac:
  pulled that night's `cairn-2026-08-15.db` off the Pi, verified
  `PRAGMA integrity_check` → `ok`, booted the API locally against the
  restored file (`DATABASE_PATH` override), confirmed `/api/health` ok
  and authenticated reads served. Not yet rehearsed: a full Scenario B
  bare-metal rebuild (needs spare hardware), and any layer-3 offsite
  restore (layer 3 did not exist at the time — see the pending entry
  above).
