"""add_twitter_oauth_columns

Revision ID: e5a1b3c7d920
Revises: 7021957c0b78
Create Date: 2026-03-22 22:50:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5a1b3c7d920"
down_revision: Union[str, Sequence[str], None] = "7021957c0b78"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("creators", schema=None) as batch_op:
        batch_op.add_column(sa.Column("twitter_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("twitter_handle", sa.String(length=128), nullable=True))
        batch_op.create_index(batch_op.f("ix_creators_twitter_id"), ["twitter_id"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("creators", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_creators_twitter_id"))
        batch_op.drop_column("twitter_handle")
        batch_op.drop_column("twitter_id")
