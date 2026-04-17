"""Add append-only enforcement trigger on signals table

Revision ID: e1a2b3c4d5f6
Revises: 2cfb0e3dd9e3
Create Date: 2026-04-17 00:00:00.000000

Postgres only — SQLite relies on application-level convention.
The trigger allows outcome resolution (NULL → WIN/LOSS/NEUTRAL) once,
but prevents: DELETEs, core-field mutations, and re-resolving outcomes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e1a2b3c4d5f6"
down_revision: str | Sequence[str] | None = "2cfb0e3dd9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add append-only trigger (Postgres only)."""
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("""
CREATE OR REPLACE FUNCTION enforce_signals_append_only()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION
      'signals table is append-only: DELETE is not permitted (signal_id=%)', OLD.signal_id;
  END IF;

  IF TG_OP = 'UPDATE' THEN
    -- Outcome may only be set once (NULL -> resolved value).
    IF OLD.outcome IS NOT NULL THEN
      RAISE EXCEPTION
        'signals table is append-only: outcome cannot be changed once set (signal_id=%)',
        OLD.signal_id;
    END IF;

    -- Core signal fields must never change.
    IF NEW.asset            IS DISTINCT FROM OLD.asset            OR
       NEW.action           IS DISTINCT FROM OLD.action           OR
       NEW.confidence       IS DISTINCT FROM OLD.confidence       OR
       NEW.reasoning        IS DISTINCT FROM OLD.reasoning        OR
       NEW.commitment_hash  IS DISTINCT FROM OLD.commitment_hash  OR
       NEW.creator_id       IS DISTINCT FROM OLD.creator_id
    THEN
      RAISE EXCEPTION
        'signals table is append-only: core signal fields cannot be modified (signal_id=%)',
        OLD.signal_id;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER signals_append_only
BEFORE UPDATE OR DELETE ON signals
FOR EACH ROW EXECUTE FUNCTION enforce_signals_append_only();
""")


def downgrade() -> None:
    """Remove append-only trigger (Postgres only)."""
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("DROP TRIGGER IF EXISTS signals_append_only ON signals;")
    op.execute("DROP FUNCTION IF EXISTS enforce_signals_append_only();")
