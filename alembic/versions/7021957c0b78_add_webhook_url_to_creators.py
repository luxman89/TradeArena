"""add_webhook_url_to_creators

Revision ID: 7021957c0b78
Revises: c4f2d8e19a37
Create Date: 2026-03-22 22:08:30.069890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7021957c0b78'
down_revision: Union[str, Sequence[str], None] = 'c4f2d8e19a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('creators', schema=None) as batch_op:
        batch_op.add_column(sa.Column('webhook_url', sa.String(length=512), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('creators', schema=None) as batch_op:
        batch_op.drop_column('webhook_url')
