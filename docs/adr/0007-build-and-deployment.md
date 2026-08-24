# 0007 — Build and deployment

**Status:** accepted
**Date:** 2026-08-15

## Context
Development happens on the Mac, the Pi runs the result. Confirmed by SSH: the
Pi is arm64 (Pi 5, Ubuntu 24.04, Docker 29 / Compose v5). The dev Mac is also
`arm64` (Apple Silicon) — both machines are the *same* architecture, which
removes an option that would otherwise be necessary.

## Options considered
- **Native build on the Pi** — `git pull` + `docker compose build` on-device.
- **Cross-build via buildx/QEMU on the Mac** — the usual answer when dev and
  prod architectures differ.
- **Native build on the Mac + local registry on the Pi** — proposed here.

## Decision
Build images natively on the Mac (`docker build`, default platform =
`linux/arm64`, which is native since the Mac is Apple Silicon — no QEMU, no
emulation penalty), push to a small `registry:2` container running on the Pi
itself (LAN-only, no external registry account, consistent with the
no-internet-facing-service constraint), then `docker compose pull && docker
compose up -d` on the Pi via a one-line SSH deploy script.

## Rationale
The reason this isn't "cross-build" is that there's nothing to cross —
Apple Silicon and Pi 5 are both arm64, so a plain `docker build` on the Mac
already produces a Pi-runnable image at full native speed. That eliminates
QEMU entirely, which is usually the slowest, flakiest part of a Mac→Pi
pipeline. Building on the Pi itself was the other real option: simpler
mentally (no registry), but ties every iteration to the Pi being up and
reachable, uses its limited RAM/CPU for `tsc`/`rollup`/wheel builds instead
of just running the app, and means a bad build can leave the production box
in a half-built state. A tiny local registry costs one more container
(`registry:2` is a few MB idle) and buys clean versioned images, a trivial
rollback (`docker compose pull` to a previous tag), and a Pi that only ever
does `pull` + `run`, never `build`.

## Consequences
Makes easy: fast iteration (native build speed on the Mac), simple rollback
by tag, Pi stays a pure runtime target. Makes hard: one more service
(registry) to keep healthy, though its failure mode is just "deploys stop
working," not data loss — acceptable. Revisit if the Mac is ever swapped for
an Intel machine, at which point this ADR's central premise (same arch on
both ends) breaks and buildx/QEMU becomes the honest answer.
