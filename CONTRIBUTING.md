# Contributing

Cairn is a personal, single-user project, published so the design and the
agent workflow can be read. **It is not looking for feature contributions**,
and pull requests that add scope will most likely be declined — please don't
spend an evening on one without asking first.

What is genuinely welcome:

- **Bug reports**, especially anything where a number is wrong. A wrong number
  is the failure mode this project cares about most.
- **Corrections to the documentation** — the spec and the ADRs are meant to
  stay true, and they drift.
- **Questions** about how something is put together. Open an issue.

If you do send a change:

- Read [AGENTS.md](AGENTS.md) first — the hard rules there are not stylistic.
  Money is never a float, holdings are always derived from transactions, and
  no real amounts, balances, ISINs or holdings appear anywhere in the repo.
- Anything that calculates needs a test, and the test comes first.
- Schema changes go through Alembic, never hand-edited SQL.
- New dependencies need a one-line justification in the commit message.
- `pytest -q` in `backend/` and `npm test && npm run lint` in `frontend/` both
  pass before you push. CI runs the same.

## Forking it for yourself

That is the expected use. Cairn is [GPL-3.0](LICENSE) — a fork you distribute
has to stay open, but running your own copy on your own hardware carries no
obligation at all. Start with the quickstart in the [README](README.md).
