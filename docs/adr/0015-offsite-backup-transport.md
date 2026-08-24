# 0015 — Offsite backup transport to the NAS

**Status:** accepted
**Date:** 2026-08-22

## Context
Spec 6.6 defines three backup layers; only two were ever built. Layer 3
(offsite, 3-2-1) was deferred in ADR 0012 "until NAS/cloud details exist",
and `docs/disaster-recovery.md` has carried the consequence as a known gap
ever since: a dead or stolen Pi loses everything since the last time a
backup was copied off the device by hand.

A dedicated backup user and a shared folder with 50 GB reserved now exist on
the Synology, which is the missing detail. This decides the Pi → NAS half.
The NAS → cloud half already exists as a weekly DSM job outside this
repository, so this ADR completes 3-2-1 rather than leaving it half-built —
but it also means the off-site leg's encryption, retention and restore path
are not described anywhere in here, and have not been verified from here.

One constraint binds harder than it looks: **DSM permits SSH login only for
members of the `administrators` group**. The obvious transport — `rsync` over
SSH — therefore requires promoting the backup user to admin, which discards
the entire point of having created a restricted user for this.

## Options considered
- **rsync over SSH.** The default answer for Linux → anything, and the one
  the spec sketches. Ruled out by the constraint above, not on merit.
- **DSM's rsync service in daemon mode.** Purpose-built as a backup target,
  needs no SSH, no shell and no mount that can go stale, and its exit code is
  a clean success signal. But daemon-mode rsync is unauthenticated-in-transit:
  the password and the payload — a complete financial picture — cross the LAN
  in cleartext.
- **NFS export.** Robust and fast, with ordinary Unix permissions. But DSM
  authorises NFS per shared folder *by IP address*: the backup user plays no
  part at all, and anything that can take that IP on the LAN gets the share.
- **SMB mount on the Pi** — chosen.

Second axis, orthogonal to transport: **plain mirrored files** versus a
**restic repository**. restic would bring encryption at rest, deduplication,
the spec's 7/4/12 retention as a one-liner, and would make the eventual cloud
leg a copy of an already-encrypted repo.

## Decision
A CIFS mount of the Synology share on the Pi at `/srv/cairn/nas`, using the
restricted backup user, with SMB3 transfer encryption (`seal`) and an
automount unit. `scripts/backup.sh` gains a third leg that mirrors the
nightly `.db` snapshot, the logical export and the deploy-time
`pre-migration-*.db` snapshots, then verifies them **on the NAS side** before
recording success.

**Plain files, not restic.** Retention is a flat 180-day window on daily
snapshots, first-of-month snapshots held for five years, deploy snapshots for
one year, and logical exports never pruned at all.

The offsite leg reports through its own marker file (`last_offsite_success`),
its own `/api/health` field and its own data-quality issue kinds, on a 72-hour
staleness threshold rather than the local backup's 48.

## Rationale
SMB is the only transport that actually uses the restricted user without
either weakening it (SSH needs admin) or ignoring it (NFS authorises by IP),
and it is the only one of the three that encrypts in transit.

Plain files won over restic on the thing that matters most at 03:00 on a bad
day: **restore is `cp`**. restic would add a repository password whose loss
destroys every backup at once, and would put a tool between a panicking human
and their data at the exact moment neither is at its best. What was given up
is real and should be named: **this is a knowing deviation from spec 6.4's
"nightly backup, encrypted, to the NAS"** — the files sit readable on the
share. The trade accepted is at-rest encryption on hardware already inside the
home, in exchange for a recovery path that cannot fail for want of a password.
A Synology encrypted shared folder can close it later without touching code.

Retention ignores spec 6.6's 7/4/12 in the generous direction. At this data
size 50 GB holds years, so space is not the binding constraint — *reach* is.
Slow corruption surfaces weeks or months later, and at that point the copy
that saves you is an old one; more recent copies of an already-corrupt file
protect nothing. Two `find` lines buy six months of daily and five years of
monthly reach, which is both more protection and less code than a real
grandfather-father-son implementation would be — and ADR 0009 asks that this
script stay short enough to review.

Two properties are load-bearing and easy to lose in a later edit:
- **No `--delete` on the rsync.** A mirror faithfully replicates the Pi's
  disasters. Without this the NAS copy is not a backup, it is a second copy of
  whatever just went wrong.
- **`findmnt --types cifs` before writing.** Writing into an unmounted
  directory would fill the Pi's own disk while every status file reported a
  healthy offsite backup — precisely the silent failure this layer exists to
  end.

The separate health signal follows ADR 0012's reasoning rather than
contradicting it: a NAS that is asleep must not make the dashboard claim there
is no backup at all, and a healthy local backup must not hide an offsite leg
that quietly stopped months ago.

## Consequences
Makes easy: a dead or stolen Pi is now recoverable, which it simply was not
before, and with the NAS's own weekly cloud job the 3-2-1 rule is satisfied
end to end.
Makes hard: the backup now depends on a mount, so the script carries timeouts
and a mount-verification guard it did not need before. It also depends on two
pieces of DSM configuration this repository cannot enforce or even see: the
share's **Recycle Bin must be off** (or on a deletion schedule), because
otherwise retention frees nothing — deleted snapshots move to `#recycle` and
go on consuming the quota until the share fills and the offsite leg starts
failing; and SMB **transfer encryption must be enabled**, or the `seal` mount
option is rejected. The NAS copy is
unencrypted at rest — the one thing to revisit, and the reason to prefer a
Synology encrypted shared folder if the NAS ever leaves the house or gains
users. Btrfs snapshots on the shared folder are assumed as the defence against
the Pi mirroring corruption or its credentials being abused; that is NAS-side
configuration this repository cannot enforce.
