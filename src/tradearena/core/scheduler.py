"""Tournament scheduler — creates recurring tournaments from schedule configs.

Called by the background loop. Checks active schedules where next_run_at <= now,
creates a tournament, auto-enrolls eligible creators, and advances next_run_at.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from tradearena.db.database import (
    CreatorORM,
    CreatorScoreORM,
    LeagueStandingORM,
    TournamentEntryORM,
    TournamentORM,
    TournamentScheduleORM,
)

logger = logging.getLogger(__name__)


def compute_next_run(schedule: TournamentScheduleORM, after: datetime) -> datetime:
    """Compute the next run time after `after` based on recurrence."""
    if schedule.recurrence == "daily":
        candidate = after.replace(hour=schedule.hour, minute=0, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate

    if schedule.recurrence == "weekly":
        dow = schedule.day_of_week if schedule.day_of_week is not None else 0
        candidate = after.replace(hour=schedule.hour, minute=0, second=0, microsecond=0)
        # Move to next occurrence of the target day
        days_ahead = (dow - candidate.weekday()) % 7
        if days_ahead == 0 and candidate <= after:
            days_ahead = 7
        candidate += timedelta(days=days_ahead)
        return candidate

    # custom — default to daily if no cron expression provided
    candidate = after.replace(hour=schedule.hour, minute=0, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def run_scheduled_tournaments(db: Session) -> int:
    """Check all active schedules and create tournaments where due.

    Returns the number of tournaments created.
    """
    now = datetime.now(UTC)
    due_schedules = (
        db.query(TournamentScheduleORM)
        .filter(
            TournamentScheduleORM.is_active.is_(True),
            TournamentScheduleORM.next_run_at <= now,
        )
        .all()
    )

    created = 0
    for schedule in due_schedules:
        try:
            tournament = _create_from_schedule(schedule, db, now)
            if tournament:
                created += 1
                logger.info(
                    "Scheduled tournament created: %s (schedule=%s)",
                    tournament.name,
                    schedule.name,
                )
        except Exception:
            logger.exception("Failed to create tournament for schedule %s", schedule.id)

        # Always advance next_run_at even on failure to avoid tight retry loops
        schedule.last_run_at = now
        schedule.next_run_at = compute_next_run(schedule, now)

    if due_schedules:
        db.commit()

    return created


def _create_from_schedule(
    schedule: TournamentScheduleORM, db: Session, now: datetime
) -> TournamentORM | None:
    """Create a tournament and auto-enroll eligible creators."""
    # Find eligible creators
    query = db.query(CreatorORM)
    if schedule.division:
        query = query.filter(CreatorORM.division == schedule.division)

    candidates = query.all()

    # Filter by min_signals
    eligible = []
    for creator in candidates:
        score = db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == creator.id).first()
        if score and score.total_signals >= schedule.min_signals:
            eligible.append(creator)

    if len(eligible) < 2:
        logger.info(
            "Schedule %s: only %d eligible creators, skipping",
            schedule.name,
            len(eligible),
        )
        return None

    # Cap at max_participants
    if len(eligible) > schedule.max_participants:
        # Sort by composite_score descending, take top N
        score_map = {}
        for c in eligible:
            s = db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == c.id).first()
            score_map[c.id] = s.composite_score if s else 0.0
        eligible.sort(key=lambda c: score_map[c.id], reverse=True)
        eligible = eligible[: schedule.max_participants]

    # Determine name suffix
    if schedule.recurrence == "daily":
        suffix = now.strftime("%Y-%m-%d")
    elif schedule.recurrence == "weekly":
        suffix = f"Week {now.isocalendar()[1]} {now.year}"
    else:
        suffix = now.strftime("%Y-%m-%d %H:%M")

    tournament = TournamentORM(
        id=uuid.uuid4().hex,
        name=f"{schedule.name} — {suffix}",
        format=schedule.format,
        status="registering",
        max_participants=schedule.max_participants,
        current_round=0,
        start_time=now,
        created_by=schedule.created_by,
        created_at=now,
    )
    db.add(tournament)
    db.flush()  # get the ID

    for i, creator in enumerate(eligible):
        entry = TournamentEntryORM(
            tournament_id=tournament.id,
            creator_id=creator.id,
            seed=i + 1,
        )
        db.add(entry)

    return tournament


def update_league_standings(schedule_id: str, tournament: TournamentORM, db: Session) -> None:
    """Update league standings after a tournament completes."""
    now = datetime.now(UTC)
    entries = (
        db.query(TournamentEntryORM).filter(TournamentEntryORM.tournament_id == tournament.id).all()
    )

    # Determine winner (last one standing in elimination, most points in RR)
    if tournament.format == "single_elimination":
        winner_entries = [e for e in entries if e.eliminated_at is None]
        winner_id = winner_entries[0].creator_id if winner_entries else None
    else:
        # Round robin — highest points
        winner_entry = max(entries, key=lambda e: e.points, default=None)
        winner_id = winner_entry.creator_id if winner_entry else None

    for entry in entries:
        standing = (
            db.query(LeagueStandingORM)
            .filter(
                LeagueStandingORM.schedule_id == schedule_id,
                LeagueStandingORM.creator_id == entry.creator_id,
            )
            .first()
        )
        if not standing:
            standing = LeagueStandingORM(
                schedule_id=schedule_id,
                creator_id=entry.creator_id,
                tournaments_played=0,
                tournaments_won=0,
                total_points=0,
                updated_at=now,
            )
            db.add(standing)

        standing.tournaments_played += 1
        standing.total_points += entry.points
        if entry.creator_id == winner_id:
            standing.tournaments_won += 1
        standing.updated_at = now

    db.commit()
