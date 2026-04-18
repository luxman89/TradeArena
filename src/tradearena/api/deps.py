"""FastAPI dependencies — authentication and DB session."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid

import bcrypt as _bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from tradearena.db.database import get_db

_logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False)

_DEFAULT_SECRET = "dev-insecure-key"
SECRET_KEY = os.getenv("TRADEARENA_SECRET_KEY", _DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 1  # Short-lived; use /auth/refresh to extend sessions

if SECRET_KEY == _DEFAULT_SECRET or SECRET_KEY == "change-me-in-production":
    if os.getenv("ENFORCE_HTTPS", "").strip() == "1":
        raise RuntimeError(
            "TRADEARENA_SECRET_KEY is set to an insecure default. "
            "Set a strong random value before running in production."
        )
    _logger.warning(
        "TRADEARENA_SECRET_KEY is using the default insecure value — "
        "do NOT use this in production. Set a strong random key."
    )

# ---------------------------------------------------------------------------
# JWT blacklist — Redis-backed (tokens invalidated via /auth/logout)
# ---------------------------------------------------------------------------

_blacklist_redis = None


def _get_blacklist_redis():
    global _blacklist_redis  # noqa: PLW0603
    if _blacklist_redis is not None:
        return _blacklist_redis
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        return None
    try:
        import redis as _redis

        client = _redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _blacklist_redis = client
        return _blacklist_redis
    except Exception as exc:
        _logger.warning(
            "JWT blacklist: Redis unavailable (%s) — logout won't persist across restarts", exc
        )
        return None


# In-memory fallback for blacklisted jtis (cleared on restart)
_mem_blacklist: set[str] = set()


def blacklist_jti(jti: str, ttl_seconds: int) -> None:
    """Add a jti to the blacklist. Redis-backed with in-memory fallback."""
    r = _get_blacklist_redis()
    if r is not None:
        try:
            r.setex(f"jti:bl:{jti}", ttl_seconds, "1")
            return
        except Exception as exc:
            _logger.warning("Failed to blacklist jti in Redis (%s) — using memory fallback", exc)
    _mem_blacklist.add(jti)


def is_jti_blacklisted(jti: str) -> bool:
    """Return True if this jti has been revoked."""
    r = _get_blacklist_redis()
    if r is not None:
        try:
            return bool(r.exists(f"jti:bl:{jti}"))
        except Exception as exc:
            _logger.warning("Failed to check jti blacklist in Redis (%s) — checking memory", exc)
    return jti in _mem_blacklist


# ---------------------------------------------------------------------------
# Admin token gate
# ---------------------------------------------------------------------------


def require_admin_token(authorization: str = Header(default="")) -> None:
    """Bearer-token gate for admin and oracle endpoints."""
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or len(expected) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access not configured on this server",
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <token> required",
        )
    token = authorization[7:]
    if not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin token",
        )


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_jwt(creator_id: str) -> str:
    """Create a signed JWT for the given creator_id (expires in JWT_EXPIRY_HOURS)."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    payload = {
        "sub": creator_id,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
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
        jti: str = payload.get("jti", "")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if jti and is_jti_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked"
        )

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
    """Dependency for POST endpoints that require authentication."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required",
        )

    from tradearena.db.database import CreatorORM

    # Dev plaintext path (seed data only — null in production)
    creator = db.query(CreatorORM).filter(CreatorORM.api_key_dev == api_key).first()
    if creator:
        return creator.id

    # Look up by SHA-256 (indexed; bcrypt cannot be used for DB lookup)
    key_hash = _hash_key(api_key)
    creator = db.query(CreatorORM).filter(CreatorORM.api_key_hash == key_hash).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or unknown API key",
        )

    # Verify v2 (bcrypt) when present; lazy-upgrade to v2 when absent
    if creator.api_key_hash_v2:
        if not _bcrypt.checkpw(api_key.encode(), creator.api_key_hash_v2.encode()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or unknown API key",
            )
    else:
        # SHA-256 match confirmed above — write bcrypt hash for next time
        creator.api_key_hash_v2 = _bcrypt.hashpw(api_key.encode(), _bcrypt.gensalt()).decode()
        try:
            db.commit()
        except Exception:
            db.rollback()

    return creator.id
