# 0017 — In-app agent for statements and screenshots

**Status:** accepted
**Date:** 2026-10-31

## Context
Recurring bookings (ADR 0016) leave one manual step: reading the brokers'
statements every couple of months and confirming or correcting what was
booked. So far that happens through an agent on the developer machine
(Claude Code + the MCP server), which needs that machine, a terminal and a
subscription session. The goal is to do it from the app itself, on any
device: paste screenshots, review, done.

## Options considered
- **Keep the MCP workflow only.** Works, but not from a phone, and not
  without the dev machine.
- **Claude Agent SDK on the Pi.** Brings a full coding harness (files, shell)
  that this job must not have, and the Pi's container is read-only.
- **Messages API with our own small tool set** — chosen. Every tool is ours,
  so what the agent can reach is exactly what the tool list says.

## Decision
- `/api/agent/*`, page **Assistant** in the UI. A conversation is stored as
  the exact Messages API history (`agent_conversation`), screenshots included.
- **Tools:** read-only views of accounts, instruments, positions,
  transactions and recurring rules; plus `propose_changes`. That is all —
  no accounts, instruments, loans, rules, settings, files, shell or web.
- **The agent never writes.** `propose_changes` validates the creates,
  updates and deletes with the same code as `/api/transactions` (applied in
  a throwaway session, rolled back) and stores an `agent_proposal`. A
  person applies or rejects it in the UI; applying re-validates against
  the ledger as it is then, writes everything in one transaction
  (`source = agent`, one import batch) and refreshes the snapshots right
  away. The agent learns the outcome at the start of the next message.
- **Model:** `claude-sonnet-5-5` by default (`AGENT_MODEL` to change).
  Reading a statement and booking a handful of rows is well within it, and
  every change is reviewed by a person before it lands anyway; Opus would
  roughly double the cost for no visible gain here. Adaptive thinking,
  effort `high`, prompt caching, server-side refusal fallback. One user message may take at most 16 model calls.
- **Credentials:** `ANTHROPIC_API_KEY` in `/srv/cairn/config/.env` on the
  Pi only. Unset = the page says so and nothing else changes. The key
  belongs to a dedicated Console workspace with prepaid credit, auto-reload
  off and a monthly spend limit — the cap is enforced by Anthropic, not by
  this code.

## Consequences
- **The app now holds a credential and sends data out.** AGENTS.md's "holds
  no credentials" no longer holds literally. The key can only spend prepaid
  credit up to the workspace limit — it moves no money of the household's —
  so the worst case stays disclosure plus a capped bill, not loss. But
  ledger excerpts and screenshots do leave the LAN for Anthropic's API
  while the agent is used. Not using the page sends nothing.
- A prompt injection in a screenshot can at most produce a bad proposal,
  which a person has to apply.
- Conversations with screenshots end up in the database and its backups.
  They can be deleted from the page.
- A turn runs inside the HTTP request (seconds to a couple of minutes).
  Fine for one user behind Caddy, which sets no proxy timeout.
