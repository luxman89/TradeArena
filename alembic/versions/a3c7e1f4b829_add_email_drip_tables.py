"""add_email_drip_tables

Revision ID: a3c7e1f4b829
Revises: 0996aff93fe7
Create Date: 2026-03-21 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c7e1f4b829"
down_revision: str | Sequence[str] | None = "0996aff93fe7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add unsubscribe_token and email_opted_out to creators, create email_events table."""
    # Add email opt-out columns to creators
    with op.batch_alter_table("creators", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("unsubscribe_token", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "email_opted_out", sa.Boolean(), nullable=False, server_default="0"
            )
        )
        batch_op.create_index(
            batch_op.f("ix_creators_unsubscribe_token"),
            ["unsubscribe_token"],
            unique=True,
        )

    # Create email_events table
    op.create_table(
        "email_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="sent"),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("clicked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "step IN ('welcome', 'first_score', 'battle_invite', 'weekly_recap')",
            name="ck_email_step",
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'failed')",
            name="ck_email_status",
        ),
    )
    op.create_index("ix_email_events_creator_id", "email_events", ["creator_id"])
    op.create_index("ix_email_events_step", "email_events", ["step"])


def downgrade() -> None:
    """Remove email_events table and email columns from creators."""
    op.drop_index("ix_email_events_step", table_name="email_events")
    op.drop_index("ix_email_events_creator_id", table_name="email_events")
    op.drop_table("email_events")

    with op.batch_alter_table("creators", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_creators_unsubscribe_token"))
        batch_op.drop_column("email_opted_out")
        batch_op.drop_column("unsubscribe_token")
