"""add_google_oauth_column

Revision ID: f8b2d4e6a193
Revises: e5a1b3c7d920
Create Date: 2026-03-22 23:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8b2d4e6a193"
down_revision: Union[str, Sequence[str], None] = "e5a1b3c7d920"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("creators", schema=None) as batch_op:
        batch_op.add_column(sa.Column("google_id", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_creators_google_id"), ["google_id"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("creators", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_creators_google_id"))
        batch_op.drop_column("google_id")
