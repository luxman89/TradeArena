"""add signal commitment nonce

Revision ID: 7d4a9f2c1e60
Revises: 8bab8229bd92
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7d4a9f2c1e60"
down_revision: str | Sequence[str] | None = "8bab8229bd92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing commitments cannot be recovered because their random nonce was
    # discarded. Keep those rows NULL while persisting every new nonce.
    op.add_column("signals", sa.Column("nonce", sa.String(length=32), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
CREATE OR REPLACE FUNCTION enforce_signals_append_only()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION
      'signals table is append-only: DELETE is not permitted (signal_id=%)', OLD.signal_id;
  END IF;

  IF TG_OP = 'UPDATE' THEN
    IF OLD.outcome IS NOT NULL THEN
      RAISE EXCEPTION
        'signals table is append-only: outcome cannot be changed once set (signal_id=%)',
        OLD.signal_id;
    END IF;

    IF NEW.signal_id       IS DISTINCT FROM OLD.signal_id       OR
       NEW.creator_id      IS DISTINCT FROM OLD.creator_id      OR
       NEW.asset           IS DISTINCT FROM OLD.asset           OR
       NEW.asset_type      IS DISTINCT FROM OLD.asset_type      OR
       NEW.action          IS DISTINCT FROM OLD.action          OR
       NEW.confidence      IS DISTINCT FROM OLD.confidence      OR
       NEW.reasoning       IS DISTINCT FROM OLD.reasoning       OR
       NEW.supporting_data IS DISTINCT FROM OLD.supporting_data OR
       NEW.target_price    IS DISTINCT FROM OLD.target_price    OR
       NEW.stop_loss       IS DISTINCT FROM OLD.stop_loss       OR
       NEW.timeframe       IS DISTINCT FROM OLD.timeframe       OR
       NEW.nonce           IS DISTINCT FROM OLD.nonce           OR
       NEW.commitment_hash IS DISTINCT FROM OLD.commitment_hash OR
       NEW.committed_at    IS DISTINCT FROM OLD.committed_at    OR
       NEW.ai_assisted     IS DISTINCT FROM OLD.ai_assisted
    THEN
      RAISE EXCEPTION
        'signals table is append-only: core signal fields cannot be modified (signal_id=%)',
        OLD.signal_id;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;
""")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # The previous trigger function must stop referencing nonce before the
        # column can be removed.
        op.execute("""
CREATE OR REPLACE FUNCTION enforce_signals_append_only()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION
      'signals table is append-only: DELETE is not permitted (signal_id=%)', OLD.signal_id;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.outcome IS NOT NULL THEN
      RAISE EXCEPTION
        'signals table is append-only: outcome cannot be changed once set (signal_id=%)',
        OLD.signal_id;
    END IF;
    IF NEW.asset IS DISTINCT FROM OLD.asset OR
       NEW.action IS DISTINCT FROM OLD.action OR
       NEW.confidence IS DISTINCT FROM OLD.confidence OR
       NEW.reasoning IS DISTINCT FROM OLD.reasoning OR
       NEW.commitment_hash IS DISTINCT FROM OLD.commitment_hash OR
       NEW.creator_id IS DISTINCT FROM OLD.creator_id
    THEN
      RAISE EXCEPTION
        'signals table is append-only: core signal fields cannot be modified (signal_id=%)',
        OLD.signal_id;
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
""")
    op.drop_column("signals", "nonce")
