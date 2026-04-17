"""Add streak_days and last_signal_day to creators table

Revision ID: a9c1e2f3b4d5
Revises: e1a2b3c4d5f6
Create Date: 2026-04-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c1e2f3b4d5"
down_revision: str | Sequence[str] | None = "e1a2b3c4d5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("creators", sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("creators", sa.Column("last_signal_day", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("creators", "last_signal_day")
    op.drop_column("creators", "streak_days")
