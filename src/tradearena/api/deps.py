"""FastAPI dependencies — authentication and DB session."""

from __future__ import annotations

import hashlib
import os

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from tradearena.db.database import get_db

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False)

_DEFAULT_SECRET = "dev-insecure-key"
SECRET_KEY = os.getenv("TRADEARENA_SECRET_KEY", _DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

if SECRET_KEY == _DEFAULT_SECRET or SECRET_KEY == "change-me-in-production":
    import logging as _logging

    _logger = _logging.getLogger(__name__)
    if os.getenv("ENFORCE_HTTPS", "").strip() == "1":
        raise RuntimeError(
            "TRADEARENA_SECRET_KEY is set to an insecure default. "
            "Set a strong random value before running in production."
        )
    _logger.warning(
        "TRADEARENA_SECRET_KEY is using the default insecure value — "
        "do NOT use this in production. Set a strong random key."
    )


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_jwt(creator_id: str) -> str:
    """Create a signed JWT for the given creator_id."""
    from datetime import UTC, datetime, timedelta

    payload = {
        "sub": creator_id,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


async def require_jwt_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_BEARER),
    db: Session = Depends(get_db),
) -> str:
    """Dependency for web-UI endpoints that use JWT Bearer auth.

    Returns the authenticated creator_id.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with Bearer token is required",
        )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        creator_id: str = payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    from tradearena.db.database import CreatorORM

    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator not found",
        )
    return creator.id


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
