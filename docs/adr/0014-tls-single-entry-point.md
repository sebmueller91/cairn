# 0014 — TLS and the single entry point

**Status:** accepted
**Date:** 2026-08-15

## Context
Service workers only run in a secure context — no HTTPS, no offline cache, no
installable PWA, even on the LAN (spec 6.3). `http://raspberrypi5` doesn't
qualify. Phase 0's docker-compose published the API container's port
directly for pipeline verification; that was explicitly a placeholder
(ADR 0007) pending this decision.

## Options considered
- **A domain you own + Let's Encrypt DNS-01 via Caddy** (spec's recommended
  route) — a real certificate, no per-device trust install, but requires
  owning a registrable domain and a DNS provider with an API. Asked the
  user directly: no domain exists, and the Pi is reached purely by the
  local name the router resolves (`$PI_NAME` → `$PI_FQDN` → `$PI_LAN_IP`).
  Buying a domain solely for this was offered and declined.
- **A local mkcert CA** (spec's stated alternative) — no domain, no ongoing
  cost, works entirely offline. Cost is per-device friction: the mkcert root
  CA has to be installed and trusted on every phone/laptop that should see
  the app as secure, manually on iOS. Chosen.
- **Defer HTTPS, stay on plain HTTP** — was offered as a third option;
  declined in favor of actually getting the PWA/offline features working
  now rather than leaving phase 6 half-finished.

## Decision
`mkcert` generates a local CA on the dev Mac and a leaf certificate for
every name a LAN device might use to reach the Pi — its short hostname,
its router-resolved FQDN and its LAN address, plus `localhost` for local
testing. Caddy terminates TLS with that certificate and becomes the
**only** published entry point (spec 6.4): the api container no longer
binds a host port at all (`expose: 8000` on the compose network only,
reachable from Caddy as `api:8000`), and Caddy also serves the built
frontend as static files with SPA fallback (`try_files … /index.html`).
`:80` gets a permanent redirect to `:443`, nothing else. `auto_https off`
in the Caddyfile because there's no domain for Caddy's automatic-HTTPS
machinery to act on — the certificate is supplied manually.

The frontend build now actually ships to the Pi as part of `scripts/deploy.sh`
(`npm run build` → `rsync` to `/srv/cairn/frontend-dist`) — until this phase
the frontend was only ever run locally against the Pi's API via a dev-server
proxy, with no deployment path of its own.

## Rationale
The domain route is the better long-term answer (spec says so, and it's
right — no per-device cert install, works the moment a device joins the
network) but it's not free: it needs a resource the user doesn't have and
was unwilling to acquire just for this. mkcert is the documented fallback
for exactly this situation, and the friction it trades for is one-time per
device, not recurring.

The LAN IP is baked into the leaf cert's SAN list, which
is only stable if the Pi's DHCP lease doesn't change — worth a DHCP
reservation in the router, noted for the user rather than done here (no
router access from this environment).

## Consequences
Makes easy: the app is now reachable at a real `https://` origin with a
certificate any *trusting* device treats as valid — service worker,
install-to-homescreen, and the offline path in ADR 0005 all become
possible for the first time. Frontend deployment stops being a manual/local
affair and becomes part of the same one-line `scripts/deploy.sh`.

Makes hard: every new device needs the mkcert root CA installed once
(instructions given to the user out of band — the CA's private key never
leaves the dev Mac and is never committed). If the certificate's SAN list
ever needs to change (new hostname, IP reassignment), it's a manual
`mkcert` regeneration and redeploy, not something the app or Caddy handles
automatically the way ACME would. Revisit this ADR if a domain is ever
acquired later — swapping to DNS-01 removes the per-device trust problem
entirely and is a Caddyfile change, not a redesign.

## Note added later

The three site-local names this ADR originally spelled out — short hostname,
router FQDN, LAN address — now live in `deploy/deploy.env`, which is not in
version control. `deploy/Caddyfile.template` carries `@PI_NAME@`, `@PI_FQDN@`
and `@PI_LAN_IP@` markers that `scripts/deploy.sh` substitutes before shipping
the file to the Pi. Nothing about the decision changed; the repository simply
stopped describing one particular home network.
