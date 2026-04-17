"""GET /leaderboard and GET /leaderboard/{division} — public endpoints."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from tradearena.db.database import CreatorORM, CreatorScoreORM, SignalORM, get_db
from tradearena.models.responses import LeaderboardDivisionResponse, LeaderboardResponse

router = APIRouter()

VALID_DIVISIONS = {"crypto", "polymarket", "multi"}
MIN_RESOLVED_FOR_LEADERBOARD = 20


def _format_entry(creator: CreatorORM) -> dict:
    score = creator.score
    return {
        "creator_id": creator.id,
        "display_name": creator.display_name,
        "division": creator.division,
        "discord_id": creator.discord_id,
        "composite_score": round(score.composite_score, 4) if score else 0.0,
        "win_rate": round(score.win_rate, 4) if score else 0.0,
        "risk_adjusted_return": round(score.risk_adjusted_return, 4) if score else 0.0,
        "consistency": round(score.consistency, 4) if score else 0.0,
        "confidence_calibration": round(score.confidence_calibration, 4) if score else 0.0,
        "total_signals": score.total_signals if score else 0,
    }


def _encode_cursor(score: float, creator_id: str) -> str:
    """Encode (composite_score, creator_id) into a URL-safe cursor string."""
    raw = f"{score:.10f}|{creator_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[float, str] | None:
    """Decode a cursor string back to (composite_score, creator_id)."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        score_str, creator_id = raw.split("|", 1)
        return float(score_str), creator_id
    except Exception:
        return None


def _build_cursor_filter(cursor: str | None):
    """Build a SQLAlchemy filter for cursor-based pagination.

    Since we order by composite_score DESC, the cursor means:
    "give me rows where score < cursor_score, or score == cursor_score and id > cursor_id"
    """
    if cursor is None:
        return None
    decoded = _decode_cursor(cursor)
    if decoded is None:
        return None
    cursor_score, cursor_id = decoded
    return or_(
        CreatorScoreORM.composite_score < cursor_score,
        and_(
            CreatorScoreORM.composite_score == cursor_score,
            CreatorORM.id > cursor_id,
        ),
    )


@router.get(
    "/leaderboard",
    response_model=LeaderboardResponse,
    summary="Get global leaderboard",
)
async def get_leaderboard(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None, description="Cursor for keyset pagination"),
    db: Session = Depends(get_db),
) -> dict:
    """Return all creators sorted by composite score descending.

    Supports both offset-based and cursor-based pagination. When `cursor` is
    provided, `offset` is ignored and keyset pagination is used instead.
    """
    resolved_subq = (
        db.query(SignalORM.creator_id, func.count(SignalORM.signal_id).label("cnt"))
        .filter(SignalORM.outcome.isnot(None))
        .group_by(SignalORM.creator_id)
        .subquery()
    )
    query = (
        db.query(CreatorORM)
        .outerjoin(CreatorScoreORM, CreatorORM.id == CreatorScoreORM.creator_id)
        .join(resolved_subq, CreatorORM.id == resolved_subq.c.creator_id)
        .filter(resolved_subq.c.cnt >= MIN_RESOLVED_FOR_LEADERBOARD)
        .order_by(CreatorScoreORM.composite_score.desc().nullslast(), CreatorORM.id)
    )

    cursor_filter = _build_cursor_filter(cursor)
    if cursor_filter is not None:
        query = query.filter(cursor_filter)
        offset = 0  # cursor replaces offset
    else:
        query = query.offset(offset)

    creators = query.limit(limit).all()
    total = (
        db.query(func.count(CreatorORM.id))
        .join(resolved_subq, CreatorORM.id == resolved_subq.c.creator_id)
        .filter(resolved_subq.c.cnt >= MIN_RESOLVED_FOR_LEADERBOARD)
        .scalar()
        or 0
    )

    next_cursor = None
    if creators:
        last = creators[-1]
        last_score = last.score.composite_score if last.score else 0.0
        next_cursor = _encode_cursor(last_score, last.id)

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_cursor": next_cursor,
        "entries": [_format_entry(c) for c in creators],
    }


@router.get(
    "/leaderboard/{division}",
    response_model=LeaderboardDivisionResponse,
    summary="Get division leaderboard",
    responses={
        422: {"description": "Invalid division — must be crypto, polymarket, or multi"},
    },
)
async def get_leaderboard_division(
    division: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None, description="Cursor for keyset pagination"),
    db: Session = Depends(get_db),
) -> dict:
    """Return creators in a specific division sorted by composite score."""
    division = division.lower()
    if division not in VALID_DIVISIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"division must be one of {sorted(VALID_DIVISIONS)}",
        )
    resolved_subq = (
        db.query(SignalORM.creator_id, func.count(SignalORM.signal_id).label("cnt"))
        .filter(SignalORM.outcome.isnot(None))
        .group_by(SignalORM.creator_id)
        .subquery()
    )
    query = (
        db.query(CreatorORM)
        .filter(CreatorORM.division == division)
        .outerjoin(CreatorScoreORM, CreatorORM.id == CreatorScoreORM.creator_id)
        .join(resolved_subq, CreatorORM.id == resolved_subq.c.creator_id)
        .filter(resolved_subq.c.cnt >= MIN_RESOLVED_FOR_LEADERBOARD)
        .order_by(CreatorScoreORM.composite_score.desc().nullslast(), CreatorORM.id)
    )

    cursor_filter = _build_cursor_filter(cursor)
    if cursor_filter is not None:
        query = query.filter(cursor_filter)
        offset = 0
    else:
        query = query.offset(offset)

    creators = query.limit(limit).all()
    total = (
        db.query(func.count(CreatorORM.id))
        .filter(CreatorORM.division == division)
        .join(resolved_subq, CreatorORM.id == resolved_subq.c.creator_id)
        .filter(resolved_subq.c.cnt >= MIN_RESOLVED_FOR_LEADERBOARD)
        .scalar()
        or 0
    )

    next_cursor = None
    if creators:
        last = creators[-1]
        last_score = last.score.composite_score if last.score else 0.0
        next_cursor = _encode_cursor(last_score, last.id)

    return {
        "division": division,
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_cursor": next_cursor,
        "entries": [_format_entry(c) for c in creators],
    }
