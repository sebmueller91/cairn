"""add instrument.tax_treatment and vorabpauschale_entry

Revision ID: a3f7c21b9e04
Revises: c7a1e4b93d20
Create Date: 2026-08-24 10:00:00.000000

Two additions the tax view needs to stop reporting a number that is
simply wrong for crypto and physical metals.

`instrument.tax_treatment` is a nullable override, not a backfilled
classification: NULL means "derive it from asset_class", which is what
every existing row wants. Writing a concrete value into every row here
would freeze today's default into the data and silently ignore any
later correction to the derivation rule.

`vorabpauschale_entry` holds the advance lump sum the broker actually
debited, keyed by the year it counts against the saver's allowance.
Manual entry, same as cpi_index_point — the amount depends on the
BMF Basiszins and per-fund Teilfreistellung, neither of which this app
can fetch.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a3f7c21b9e04'
down_revision: Union[str, None] = 'c7a1e4b93d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("instrument") as batch_op:
        batch_op.add_column(
            sa.Column(
                "tax_treatment",
                sa.Enum("CAPITAL_GAINS", "PRIVATE_SALE", "NONE", name="taxtreatment"),
                nullable=True,
            )
        )

    op.create_table(
        "vorabpauschale_entry",
        sa.Column("year", sa.Integer(), nullable=False),
        # TEXT, never REAL — money is Decimal end to end (ADR 0001).
        sa.Column("amount_eur", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("year"),
    )


def downgrade() -> None:
    op.drop_table("vorabpauschale_entry")
    with op.batch_alter_table("instrument") as batch_op:
        batch_op.drop_column("tax_treatment")
