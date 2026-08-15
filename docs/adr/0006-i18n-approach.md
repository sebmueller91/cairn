# 0006 — i18n approach

**Status:** proposed
**Date:** 2026-08-15

## Context
German default, English switchable, without the translation problem leaking
into the database, the API, or enum handling — spec 8.3 already states the
four rules well; the gap is making violations (a new error code with no
translation) fail loudly instead of silently falling back to a raw key.

## Options considered
Accepting spec's `react-i18next` + JSON namespaces + `Intl` formatting
without a real alternative considered — this part of the spec is sound and
uncontroversial. The open question is only the error-code/translation
coupling.

## Decision
`react-i18next`, namespaced JSON resources (`common`, `dashboard`, `assets`,
`settings`, `errors`), German stored server-side in `setting` and mirrored to
`localStorage`, `Intl.NumberFormat`/`Intl.DateTimeFormat` for all formatting
(`en-GB` not `en-US`), CSS-variable-driven charts with a light and dark
palette. **Addition:** a single canonical `ErrorCode` enum in the backend is
the source of truth, exported into the OpenAPI schema (so agents see the
exhaustive list) and into a generated list the CI key-parity test checks
against — every `ErrorCode` value must have a matching key in *both*
`errors/de.json` and `errors/en.json`, not just parity between the two
language files.

## Rationale
Spec's key-parity test (de.json vs en.json) catches a translator forgetting a
language. It does not catch a backend developer (or agent) adding a new
`sell_exceeds_holding`-style error code without adding *any* translation for
it — that fails silently at runtime as a raw key shown to the user. Anchoring
the parity check to the backend's enum instead of just cross-checking the two
JSON files closes that gap at build time, which is where AGENTS.md wants this
kind of thing caught.

## Consequences
Makes easy: an agent adding a new validation rule gets a CI failure, not a
runtime surprise, if it forgets the German string. Makes hard: one more
generated artifact (the error code list) to keep in the build pipeline —
cheap, a single script step.
