"""Matchmaking & ELO rating endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from tradearena.core.elo import DEFAULT_RATING
from tradearena.core.matchmaker import join_queue, leave_queue
from tradearena.db.database import BotRatingORM, CreatorORM, RatingHistoryORM, get_db
from tradearena.models.rating import (
    BotRatingResponse,
    LeaderboardEloEntry,
    LeaderboardEloResponse,
    MatchmakingQueueResponse,
    RatingHistoryResponse,
)

router = APIRouter(tags=["matchmaking"])


@router.post(
    "/matchmaking/queue",
    response_model=MatchmakingQueueResponse,
    status_code=status.HTTP_200_OK,
    summary="Join matchmaking queue",
    responses={404: {"description": "Bot/creator not found"}},
)
async def join_matchmaking_queue(
    bot_id: str = Query(..., description="Bot/creator ID to queue"),
    db: Session = Depends(get_db),
) -> dict:
    """Add a bot/creator to the ELO matchmaking queue."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == bot_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{bot_id}' not found.",
        )

    join_queue(db, bot_id)
    return {"bot_id": bot_id, "queued": True, "message": "Joined matchmaking queue."}


@router.delete(
    "/matchmaking/queue",
    response_model=MatchmakingQueueResponse,
    summary="Leave matchmaking queue",
)
async def leave_matchmaking_queue(
    bot_id: str = Query(..., description="Bot/creator ID to dequeue"),
    db: Session = Depends(get_db),
) -> dict:
    """Remove a bot/creator from the matchmaking queue."""
    removed = leave_queue(db, bot_id)
    if not removed:
        return {"bot_id": bot_id, "queued": False, "message": "Not in queue."}
    return {"bot_id": bot_id, "queued": False, "message": "Left matchmaking queue."}


@router.get(
    "/bots/{bot_id}/rating",
    response_model=BotRatingResponse,
    summary="Get bot ELO rating",
    responses={404: {"description": "Bot/creator not found"}},
)
async def get_bot_rating(
    bot_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Get current ELO rating for a bot/creator."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == bot_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{bot_id}' not found.",
        )

    rating = db.query(BotRatingORM).filter(BotRatingORM.bot_id == bot_id).first()
    if not rating:
        return {
            "bot_id": bot_id,
            "elo": DEFAULT_RATING,
            "matches_played": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "updated_at": None,
        }
    return {
        "bot_id": rating.bot_id,
        "elo": rating.elo,
        "matches_played": rating.matches_played,
        "wins": rating.wins,
        "losses": rating.losses,
        "draws": rating.draws,
        "updated_at": rating.updated_at,
    }


@router.get(
    "/bots/{bot_id}/rating-history",
    response_model=RatingHistoryResponse,
    summary="Get bot ELO history",
    responses={404: {"description": "Bot/creator not found"}},
)
async def get_bot_rating_history(
    bot_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """Get ELO rating history for charting."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == bot_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{bot_id}' not found.",
        )

    history = (
        db.query(RatingHistoryORM)
        .filter(RatingHistoryORM.bot_id == bot_id)
        .order_by(RatingHistoryORM.timestamp.desc())
        .limit(limit)
        .all()
    )

    return {
        "bot_id": bot_id,
        "history": [
            {"elo": h.elo, "match_id": h.match_id, "timestamp": h.timestamp}
            for h in reversed(history)  # chronological order
        ],
    }


@router.get(
    "/leaderboard/elo",
    response_model=LeaderboardEloResponse,
    summary="ELO leaderboard",
)
async def elo_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Get ELO-ranked leaderboard."""
    query = (
        db.query(BotRatingORM, CreatorORM.display_name)
        .join(CreatorORM, BotRatingORM.bot_id == CreatorORM.id)
        .order_by(BotRatingORM.elo.desc())
    )
    total = query.count()
    rows = query.offset(offset).limit(limit).all()

    entries = [
        LeaderboardEloEntry(
            bot_id=rating.bot_id,
            display_name=display_name,
            elo=rating.elo,
            matches_played=rating.matches_played,
            wins=rating.wins,
            losses=rating.losses,
            draws=rating.draws,
        )
        for rating, display_name in rows
    ]

    return {"total": total, "entries": entries}
