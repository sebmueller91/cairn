"""add recurring_booking

Revision ID: e2b8d41f6a07
Revises: a3f7c21b9e04
Create Date: 2026-10-31 12:00:00.000000

Standing rules (savings plans, loan instalments) that the nightly job
turns into provisional transactions — see app/recurring_service.py and
ADR 0016. Configuration only: the ledger never reads this table, so
dropping it loses no derived number.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e2b8d41f6a07'
down_revision: Union[str, None] = 'a3f7c21b9e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recurring_booking",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                'BUY', 'SELL', 'DIVIDEND', 'INTEREST', 'FEE', 'TAX', 'DEPOSIT',
                'WITHDRAWAL', 'TRANSFER', 'SPLIT', 'VALUATION', 'OPENING_BALANCE',
                'BALANCE_STATEMENT', 'LOAN_PAYMENT', 'EXTRA_REPAYMENT',
                name="transactiontype",
            ),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        # TEXT, never REAL — money is Decimal end to end (ADR 0001).
        sa.Column("amount_eur", sa.Text(), nullable=True),
        sa.Column("fees", sa.Text(), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("shift_to_business_day", sa.Boolean(), nullable=False),
        sa.Column("quantity_decimals", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("booked_through", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("recurring_booking")
