"""add_discord_oauth_columns

Revision ID: a1b2c3d4e5f6
Revises: f8b2d4e6a193
Create Date: 2026-03-22 23:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f8b2d4e6a193"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("creators", schema=None) as batch_op:
        batch_op.add_column(sa.Column("discord_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("discord_username", sa.String(length=128), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_creators_discord_id"), ["discord_id"], unique=True
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("creators", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_creators_discord_id"))
        batch_op.drop_column("discord_username")
        batch_op.drop_column("discord_id")
