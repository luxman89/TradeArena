"""add tournament matches and fields

Revision ID: c4f2d8e19a37
Revises: b80988abf0e5
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f2d8e19a37"
down_revision: Union[str, None] = "b80988abf0e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: all operations (tournament_matches table, start_time/created_by columns)
    # are already performed by b80988abf0e5. This migration is kept as a chain link
    # because 7021957c0b78 depends on it.
    pass


def downgrade() -> None:
    pass
