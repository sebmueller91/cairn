# 0001 — Backend language and framework

**Status:** accepted
**Date:** 2026-08-15

## Context
The backend is mostly a validating ledger (accounting invariants, exact
decimal money) sitting behind an API that a coding agent must be able to
understand from its schema alone, running on a 4-core/8GB Pi. The person
reviewing every line is the spec's author, not a team with house conventions.

## Options considered
- **FastAPI + Pydantic v2 + SQLAlchemy 2.0 (typed) + Alembic** — spec's
  direction, adjusted (see Decision).
- **TypeScript: Fastify + Zod + Drizzle ORM + zod-to-openapi** — single
  language across front and back end, `bigint` for integer-cent money.
- **Go: net/http/chi + sqlc + goose** — smallest runtime footprint, explicit
  everything, no ORM magic to review.

## Decision
FastAPI + Pydantic v2 for the API layer, **SQLAlchemy 2.0's typed ORM instead
of SQLModel**, Alembic for migrations. Python's `decimal.Decimal` for all
money and quantity fields.

## Rationale
FastAPI's generated `/api/openapi.json` is the one piece of "agent-friendly
API" the spec asks for that comes free instead of hand-built — Zod→OpenAPI in
the TS stack works but is a library choice and a maintenance surface, not a
framework guarantee. Pydantic validation errors map directly onto the
"machine-readable error, not a sentence" requirement in 7.2. Python's
`Decimal` is exact and native, no integer-cents workaround needed to satisfy
the no-floats rule. Against Go: Go would produce a smaller, more explicit
binary, but no comparable OpenAPI-for-free story, and hand-rolled reflection
or codegen brings back the exact "agent needs the spec explained" problem
FastAPI solves. Diverging from the spec's SQLModel suggestion deliberately:
SQLModel entangles the ORM row and the API schema in one class, which is
convenient until they need to diverge — and they will, e.g. `txn` stores
`amount_eur` but the API also wants to accept `price` + `currency` and derive
it. Separate SQLAlchemy models and Pydantic schemas cost one mapping layer and
buy that flexibility, plus SQLAlchemy 2.0 typed models are the more heavily
documented, more agent-legible path when something needs debugging.

## Consequences
Makes easy: OpenAPI contract for agents and the frontend both come from the
same source of truth; ORM/API separation allows the API to stay stable while
the schema evolves. Makes hard: one extra layer (Pydantic schema ↔ SQLAlchemy
model mapping) to write and review per entity, versus SQLModel's single
class — accepted cost. Revisit if: the mapping layer turns out to be pure
boilerplate in practice with no actual divergence use, at which point SQLModel
becomes attractive again.
