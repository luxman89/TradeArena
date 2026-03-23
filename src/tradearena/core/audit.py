"""Structured audit logging for admin/privileged actions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from tradearena.db.database import AuditLogORM

logger = logging.getLogger(__name__)


def log_action(
    db: Session,
    *,
    actor: str,
    action: str,
    target: str | None = None,
    metadata: dict | None = None,
) -> AuditLogORM:
    """Record an audit log entry and commit it.

    Args:
        db: Active database session.
        actor: Who performed the action (creator_id, "system", or "admin").
        action: Action identifier, e.g. "api_key.created", "battle.force_resolved".
        target: ID of the affected entity (creator_id, battle_id, etc.).
        metadata: Optional dict with extra context.
    """
    entry = AuditLogORM(
        actor=actor,
        action=action,
        target=target,
        timestamp=datetime.now(UTC),
        metadata_=metadata,
    )
    db.add(entry)
    db.commit()
    logger.info("audit: actor=%s action=%s target=%s", actor, action, target)
    return entry
