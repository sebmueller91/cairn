"""add etf_composition.updated_at

Revision ID: c7a1e4b93d20
Revises: 0c4340728f1a
Create Date: 2026-08-16 22:40:00.000000

Fund compositions have no automatic source (docs/agent-workflows.md
workflow 7), so the only thing standing between the look-through and a
years-stale pie chart is knowing how old the numbers are.

SQLite rejects ADD COLUMN with a non-constant default, so this cannot be
a one-step add of a NOT NULL CURRENT_TIMESTAMP column: add it nullable,
backfill, then tighten. batch_alter_table recreates the table, which is
how the tightening step works at all on SQLite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c7a1e4b93d20'
down_revision: Union[str, None] = '0c4340728f1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("etf_composition") as batch_op:
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
    # Rows that predate this column were entered by hand at some unknown
    # point. Stamping them "now" would claim a freshness they don't have,
    # so they keep NULL and the data quality check reads that as unknown
    # age — which it reports, rather than staying quiet.
    with op.batch_alter_table("etf_composition") as batch_op:
        batch_op.alter_column("updated_at", nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("etf_composition") as batch_op:
        batch_op.drop_column("updated_at")
