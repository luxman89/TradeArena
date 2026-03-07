"""FastAPI dependencies — authentication and DB session."""

from __future__ import annotations

import hashlib
import os

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from tradearena.db.database import get_db

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

_SECRET_KEY = os.getenv("TRADEARENA_SECRET_KEY", "dev-insecure-key")


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def require_api_key(
    api_key: str | None = Security(API_KEY_HEADER),
    db: Session = Depends(get_db),
) -> str:
    """Dependency for POST endpoints that require authentication.

    Checks api_key_dev first (exact match, dev seed data only), then
    api_key_hash (SHA-256 match, production). This keeps seed keys working.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required",
        )

    from tradearena.db.database import CreatorORM

    # Check api_key_dev (exact match — populated by seed_demo.py for local dev only)
    creator = db.query(CreatorORM).filter(CreatorORM.api_key_dev == api_key).first()
    if not creator:
        # Check api_key_hash (SHA-256 — used in production and for registered creators)
        key_hash = _hash_key(api_key)
        creator = db.query(CreatorORM).filter(CreatorORM.api_key_hash == key_hash).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or unknown API key",
        )
    return creator.id
