"""Season utilities — weekly rolling windows (Mon 00:00 UTC → Sun 23:59:59 UTC)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def current_season_bounds() -> tuple[datetime, datetime]:
    """Return (season_start, season_end) for the current ISO week."""
    now = datetime.now(UTC)
    days_since_monday = now.weekday()  # 0 = Monday
    season_start = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    season_end = season_start + timedelta(days=7)
    return season_start, season_end


def season_label(start: datetime) -> str:
    """Human-readable label for a season start date, e.g. 'Week 16 · Apr 14'."""
    return f"Week {start.strftime('%W')} · {start.strftime('%b %-d')}"
