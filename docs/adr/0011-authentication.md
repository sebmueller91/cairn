# 0011 — Authentication

**Status:** accepted
**Date:** 2026-08-15

## Context
Single user, LAN-only, no tenancy. The API also needs to be driven directly
by an agent (curl/HTTP client), not only through the browser SPA. Token
storage location matters for XSS exposure even though there's only one user.

## Options considered
- **Static bearer token only, browser stores it in localStorage** — simplest,
  but XSS-exposed since JS can read localStorage.
- **OAuth/session framework** — no second user to distinguish, pure overhead.
- **Static token as the root of trust, two presentation paths** — proposed
  here.

## Decision
A static bearer token in `.env` (plus an optional second read-only token)
remains the root of trust, per spec. Two ways to present it: **agent/API
clients** send `Authorization: Bearer <token>` directly — no session, no
cookie, they hold the token from the password manager. **The browser SPA**
exchanges the token once, via a `POST /api/auth/session` the user submits
manually, for an `HttpOnly`, `Secure`, `SameSite=Strict` cookie; the token
itself never touches `localStorage` or any JS-readable storage after that
point. Read-only token maps to a `scope: read_only` checked against HTTP
method on every write endpoint.

## Rationale
The token is explicitly "the last line of defence, not the first" (spec
6.4) — the real defence is network isolation. But zero-cost hardening is
still worth taking: an `HttpOnly` cookie means a theoretical XSS in the
frontend can't exfiltrate the token via `document.cookie`, whereas
localStorage offers no such protection. This costs one extra endpoint and no
real complexity, since there's still exactly one credential and no user
model behind it.

## Consequences
Makes easy: agents keep the simplest possible auth (one header, one token,
no session dance); the browser gets a marginally safer storage location for
free. Makes hard: nothing meaningful — one login endpoint, one cookie check
in the auth dependency alongside the bearer-header check.
