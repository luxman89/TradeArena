"""add asset_type column to signals

Revision ID: 48e054e14852
Revises: f62832412863
Create Date: 2026-03-23 10:15:07.698117

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48e054e14852"
down_revision: str | Sequence[str] | None = "f62832412863"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add asset_type column to signals table (nullable, defaults to 'crypto')."""
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("asset_type", sa.String(length=10), nullable=True))

    # Backfill existing signals as crypto (they were all crypto before this change)
    op.execute("UPDATE signals SET asset_type = 'crypto' WHERE asset_type IS NULL")


def downgrade() -> None:
    """Remove asset_type column from signals."""
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.drop_column("asset_type")
