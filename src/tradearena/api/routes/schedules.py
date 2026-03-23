"""Tournament schedule management — create, list, update, delete schedules + league standings."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from tradearena.api.deps import require_api_key
from tradearena.core.scheduler import compute_next_run
from tradearena.db.database import (
    LeagueStandingORM,
    TournamentScheduleORM,
    get_db,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])

VALID_RECURRENCES = {"daily", "weekly", "custom"}
VALID_FORMATS = {"single_elimination", "round_robin"}


def _schedule_to_dict(s: TournamentScheduleORM) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "format": s.format,
        "recurrence": s.recurrence,
        "day_of_week": s.day_of_week,
        "hour": s.hour,
        "max_participants": s.max_participants,
        "division": s.division,
        "min_signals": s.min_signals,
        "is_active": s.is_active,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat(),
        "next_run_at": s.next_run_at.isoformat(),
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
    }


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a tournament schedule",
)
async def create_schedule(
    payload: dict,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    name = (payload.get("name") or "").strip()
    if not name or len(name) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name is required and must be <= 128 chars",
        )

    fmt = payload.get("format", "single_elimination")
    if fmt not in VALID_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"format must be one of: {sorted(VALID_FORMATS)}",
        )

    recurrence = payload.get("recurrence", "daily")
    if recurrence not in VALID_RECURRENCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"recurrence must be one of: {sorted(VALID_RECURRENCES)}",
        )

    hour = payload.get("hour", 12)
    if not isinstance(hour, int) or hour < 0 or hour > 23:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hour must be an integer 0-23",
        )

    day_of_week = payload.get("day_of_week")
    if recurrence == "weekly":
        valid_dow = isinstance(day_of_week, int) and 0 <= day_of_week <= 6
        if day_of_week is None or not valid_dow:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="day_of_week (0=Mon..6=Sun) is required for weekly schedules",
            )

    max_participants = payload.get("max_participants", 8)
    if not isinstance(max_participants, int) or max_participants < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="max_participants must be >= 2",
        )

    min_signals = payload.get("min_signals", 5)
    if not isinstance(min_signals, int) or min_signals < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_signals must be >= 0",
        )

    now = datetime.now(UTC)
    schedule = TournamentScheduleORM(
        id=uuid.uuid4().hex,
        name=name,
        format=fmt,
        recurrence=recurrence,
        day_of_week=day_of_week,
        hour=hour,
        max_participants=max_participants,
        division=payload.get("division"),
        min_signals=min_signals,
        is_active=True,
        created_by=creator_id,
        created_at=now,
        next_run_at=now,  # placeholder, computed below
        last_run_at=None,
    )
    # Compute proper next_run_at
    schedule.next_run_at = compute_next_run(schedule, now)

    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return _schedule_to_dict(schedule)


@router.get(
    "",
    summary="List tournament schedules",
)
async def list_schedules(
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(TournamentScheduleORM)
    if active_only:
        query = query.filter(TournamentScheduleORM.is_active.is_(True))
    schedules = query.order_by(TournamentScheduleORM.next_run_at.asc()).all()
    return {
        "schedules": [_schedule_to_dict(s) for s in schedules],
        "total": len(schedules),
    }


@router.get(
    "/{schedule_id}",
    summary="Get schedule details",
)
async def get_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
) -> dict:
    s = db.query(TournamentScheduleORM).filter(TournamentScheduleORM.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return _schedule_to_dict(s)


@router.patch(
    "/{schedule_id}",
    summary="Update a schedule (owner only)",
)
async def update_schedule(
    schedule_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    s = db.query(TournamentScheduleORM).filter(TournamentScheduleORM.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if s.created_by != creator_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the schedule owner")

    recompute_next = False
    if "name" in payload:
        s.name = (payload["name"] or "").strip()
    if "is_active" in payload:
        s.is_active = bool(payload["is_active"])
    if "hour" in payload:
        h = payload["hour"]
        if not isinstance(h, int) or h < 0 or h > 23:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="hour must be 0-23")
        s.hour = h
        recompute_next = True
    if "day_of_week" in payload:
        s.day_of_week = payload["day_of_week"]
        recompute_next = True
    if "max_participants" in payload:
        mp = payload["max_participants"]
        if not isinstance(mp, int) or mp < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_participants must be >= 2",
            )
        s.max_participants = mp
    if "min_signals" in payload:
        s.min_signals = payload["min_signals"]
    if "division" in payload:
        s.division = payload["division"]

    if recompute_next:
        s.next_run_at = compute_next_run(s, datetime.now(UTC))

    db.commit()
    db.refresh(s)
    return _schedule_to_dict(s)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a schedule (owner only)",
)
async def delete_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> None:
    s = db.query(TournamentScheduleORM).filter(TournamentScheduleORM.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if s.created_by != creator_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the schedule owner")
    # Clean up standings
    db.query(LeagueStandingORM).filter(LeagueStandingORM.schedule_id == schedule_id).delete()
    db.delete(s)
    db.commit()


@router.get(
    "/{schedule_id}/standings",
    summary="Get league standings for a schedule",
)
async def get_standings(
    schedule_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    s = db.query(TournamentScheduleORM).filter(TournamentScheduleORM.id == schedule_id).first()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    query = (
        db.query(LeagueStandingORM)
        .filter(LeagueStandingORM.schedule_id == schedule_id)
        .order_by(
            LeagueStandingORM.tournaments_won.desc(),
            LeagueStandingORM.total_points.desc(),
        )
    )
    total = query.count()
    standings = query.offset(offset).limit(limit).all()

    return {
        "schedule_id": schedule_id,
        "schedule_name": s.name,
        "standings": [
            {
                "creator_id": st.creator_id,
                "tournaments_played": st.tournaments_played,
                "tournaments_won": st.tournaments_won,
                "total_points": st.total_points,
                "updated_at": st.updated_at.isoformat(),
            }
            for st in standings
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
