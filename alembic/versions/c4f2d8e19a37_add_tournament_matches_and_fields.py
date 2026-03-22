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
    # Add start_time and created_by to tournaments
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(sa.Column("start_time", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("created_by", sa.String(64), sa.ForeignKey("creators.id"), nullable=True)
        )

    # Create tournament_matches table
    op.create_table(
        "tournament_matches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tournament_id",
            sa.String(64),
            sa.ForeignKey("tournaments.id"),
            nullable=False,
        ),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("match_order", sa.Integer(), nullable=False),
        sa.Column(
            "battle_id",
            sa.String(64),
            sa.ForeignKey("battles.battle_id"),
            nullable=True,
        ),
        sa.Column(
            "winner_bot_id",
            sa.String(64),
            sa.ForeignKey("creators.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_tournament_matches_tournament_id",
        "tournament_matches",
        ["tournament_id"],
    )
    op.create_index(
        "ix_tournament_matches_battle_id",
        "tournament_matches",
        ["battle_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tournament_matches_battle_id", table_name="tournament_matches")
    op.drop_index("ix_tournament_matches_tournament_id", table_name="tournament_matches")
    op.drop_table("tournament_matches")

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_column("created_by")
        batch_op.drop_column("start_time")
