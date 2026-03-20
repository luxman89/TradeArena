"""Tournament endpoints — create, join, view bracket, advance rounds."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from tradearena.db.database import (
    BattleORM,
    CreatorORM,
    TournamentEntryORM,
    TournamentORM,
    get_db,
)
from tradearena.models.tournament import (
    TournamentCreate,
    TournamentJoinRequest,
    TournamentResponse,
)

router = APIRouter(tags=["tournaments"])


def _tournament_response(t: TournamentORM) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "format": t.format,
        "status": t.status,
        "max_participants": t.max_participants,
        "current_round": t.current_round,
        "created_at": t.created_at,
        "entries": [
            {
                "creator_id": e.creator_id,
                "seed": e.seed,
                "eliminated_at": e.eliminated_at.isoformat() if e.eliminated_at else None,
                "points": e.points,
            }
            for e in t.entries
        ],
    }


@router.post(
    "/tournament",
    status_code=status.HTTP_201_CREATED,
    response_model=TournamentResponse,
    summary="Create a tournament",
)
async def create_tournament(
    payload: TournamentCreate,
    db: Session = Depends(get_db),
) -> dict:
    """Create a new tournament. Starts in 'registering' status."""
    tournament = TournamentORM(
        id=uuid.uuid4().hex,
        name=payload.name,
        format=payload.format,
        status="registering",
        max_participants=payload.max_participants,
        current_round=0,
        created_at=datetime.now(UTC),
    )
    db.add(tournament)
    db.commit()
    db.refresh(tournament)
    return _tournament_response(tournament)


@router.post(
    "/tournament/{tournament_id}/join",
    response_model=TournamentResponse,
    summary="Join a tournament",
    responses={
        404: {"description": "Tournament or creator not found"},
        409: {"description": "Already joined or tournament full/not registering"},
    },
)
async def join_tournament(
    tournament_id: str,
    payload: TournamentJoinRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Register a creator in a tournament."""
    tournament = db.query(TournamentORM).filter(TournamentORM.id == tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.status != "registering":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tournament is not accepting registrations",
        )

    creator = db.query(CreatorORM).filter(CreatorORM.id == payload.creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    existing = (
        db.query(TournamentEntryORM)
        .filter(
            TournamentEntryORM.tournament_id == tournament_id,
            TournamentEntryORM.creator_id == payload.creator_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Creator already registered in this tournament",
        )

    current_count = (
        db.query(TournamentEntryORM)
        .filter(TournamentEntryORM.tournament_id == tournament_id)
        .count()
    )
    if current_count >= tournament.max_participants:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tournament is full",
        )

    seed = current_count + 1
    entry = TournamentEntryORM(
        tournament_id=tournament_id,
        creator_id=payload.creator_id,
        seed=seed,
    )
    db.add(entry)
    db.commit()
    db.refresh(tournament)
    return _tournament_response(tournament)


@router.get(
    "/tournament/{tournament_id}",
    response_model=TournamentResponse,
    summary="Get tournament bracket state",
    responses={
        404: {"description": "Tournament not found"},
    },
)
async def get_tournament(
    tournament_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Return full tournament state including all entries."""
    tournament = db.query(TournamentORM).filter(TournamentORM.id == tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return _tournament_response(tournament)


@router.post(
    "/tournament/{tournament_id}/advance",
    response_model=TournamentResponse,
    summary="Advance tournament to next round",
    responses={
        404: {"description": "Tournament not found"},
        409: {"description": "Tournament not in progress or already completed"},
        422: {"description": "Not enough participants to advance"},
    },
)
async def advance_tournament(
    tournament_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Resolve current round and advance the tournament.

    For single_elimination: pairs active participants by seed, creates battles,
    resolves them using existing scores, and eliminates losers.
    For round_robin: creates all pairings for the current round.
    """
    tournament = db.query(TournamentORM).filter(TournamentORM.id == tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    if tournament.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tournament already completed",
        )

    # If still registering, start the tournament
    if tournament.status == "registering":
        entries = (
            db.query(TournamentEntryORM)
            .filter(TournamentEntryORM.tournament_id == tournament_id)
            .all()
        )
        if len(entries) < 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Need at least 2 participants to start",
            )
        tournament.status = "in_progress"

    if tournament.format == "single_elimination":
        _advance_single_elimination(tournament, db)
    else:
        _advance_round_robin(tournament, db)

    db.commit()
    db.refresh(tournament)
    return _tournament_response(tournament)


def _advance_single_elimination(tournament: TournamentORM, db: Session) -> None:
    """Pair active participants and eliminate losers."""
    active = (
        db.query(TournamentEntryORM)
        .filter(
            TournamentEntryORM.tournament_id == tournament.id,
            TournamentEntryORM.eliminated_at.is_(None),
        )
        .order_by(TournamentEntryORM.seed.asc())
        .all()
    )

    if len(active) < 2:
        tournament.status = "completed"
        return

    tournament.current_round += 1
    now = datetime.now(UTC)

    # Pair 1st vs last, 2nd vs second-last, etc.
    pairs = []
    n = len(active)
    for i in range(n // 2):
        pairs.append((active[i], active[n - 1 - i]))

    # If odd number, last entry gets a bye (no elimination)
    for e1, e2 in pairs:
        winner_id = _resolve_matchup(e1.creator_id, e2.creator_id, db)
        loser_entry = e2 if winner_id == e1.creator_id else e1

        # Create a battle record
        battle = BattleORM(
            battle_id=uuid.uuid4().hex,
            creator1_id=e1.creator_id,
            creator2_id=e2.creator_id,
            status="RESOLVED",
            window_days=0,
            created_at=now,
            resolved_at=now,
            winner_id=winner_id,
            battle_type="AUTO",
        )
        db.add(battle)
        loser_entry.eliminated_at = now

    # Check if only one remains
    remaining = [e for e in active if e.eliminated_at is None]
    if len(remaining) <= 1:
        tournament.status = "completed"


def _advance_round_robin(tournament: TournamentORM, db: Session) -> None:
    """One round of round-robin: each active pair plays once per round."""
    active = (
        db.query(TournamentEntryORM)
        .filter(
            TournamentEntryORM.tournament_id == tournament.id,
            TournamentEntryORM.eliminated_at.is_(None),
        )
        .order_by(TournamentEntryORM.seed.asc())
        .all()
    )

    if len(active) < 2:
        tournament.status = "completed"
        return

    tournament.current_round += 1
    now = datetime.now(UTC)
    total_rounds = len(active) - 1  # round-robin needs n-1 rounds

    # Simple round-robin: pair by rotating schedule
    n = len(active)
    for i in range(n // 2):
        e1 = active[i]
        e2 = active[n - 1 - i]
        winner_id = _resolve_matchup(e1.creator_id, e2.creator_id, db)

        battle = BattleORM(
            battle_id=uuid.uuid4().hex,
            creator1_id=e1.creator_id,
            creator2_id=e2.creator_id,
            status="RESOLVED",
            window_days=0,
            created_at=now,
            resolved_at=now,
            winner_id=winner_id,
            battle_type="AUTO",
        )
        db.add(battle)

        # Award point to winner
        winner_entry = e1 if winner_id == e1.creator_id else e2
        winner_entry.points += 1

    if tournament.current_round >= total_rounds:
        tournament.status = "completed"


def _resolve_matchup(creator1_id: str, creator2_id: str, db: Session) -> str:
    """Resolve a matchup using existing creator scores. Returns winner_id."""
    from tradearena.db.database import CreatorScoreORM

    s1 = db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == creator1_id).first()
    s2 = db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == creator2_id).first()

    score1 = s1.composite_score if s1 else 0.0
    score2 = s2.composite_score if s2 else 0.0

    return creator1_id if score1 >= score2 else creator2_id
