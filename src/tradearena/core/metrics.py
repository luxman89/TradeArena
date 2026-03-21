"""In-memory metrics collector for monitoring dashboard.

Tracks resolver runs, error counts, and latencies in a bounded ring buffer.
Resets on process restart — intentional for a lightweight approach.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class ResolverRun:
    """Record of a single oracle resolver run."""

    timestamp: float
    resolved: int
    errors: int
    skipped: int
    duration_ms: float


@dataclass
class BackgroundError:
    """Record of a background loop error."""

    timestamp: float
    component: str  # "oracle", "scoring", "battles", "matchmaking", "bots"
    message: str


class MetricsCollector:
    """Thread-safe in-memory metrics collector with bounded history."""

    def __init__(self, max_runs: int = 500, max_errors: int = 200) -> None:
        self._lock = threading.Lock()
        self._resolver_runs: deque[ResolverRun] = deque(maxlen=max_runs)
        self._errors: deque[BackgroundError] = deque(maxlen=max_errors)
        self._started_at: float = time.time()
        self._loop_iterations: int = 0

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._started_at

    def record_resolver_run(
        self, resolved: int, errors: int, skipped: int, duration_ms: float
    ) -> None:
        with self._lock:
            self._resolver_runs.append(
                ResolverRun(
                    timestamp=time.time(),
                    resolved=resolved,
                    errors=errors,
                    skipped=skipped,
                    duration_ms=duration_ms,
                )
            )

    def record_error(self, component: str, message: str) -> None:
        with self._lock:
            self._errors.append(
                BackgroundError(
                    timestamp=time.time(),
                    component=component,
                    message=message[:500],
                )
            )

    def record_loop_iteration(self) -> None:
        with self._lock:
            self._loop_iterations += 1

    def get_resolver_stats(self) -> dict:
        """Aggregate resolver statistics."""
        with self._lock:
            runs = list(self._resolver_runs)

        if not runs:
            return {
                "total_runs": 0,
                "total_resolved": 0,
                "total_errors": 0,
                "total_skipped": 0,
                "avg_duration_ms": 0.0,
                "max_duration_ms": 0.0,
                "last_run_at": None,
                "recent_runs": [],
            }

        total_resolved = sum(r.resolved for r in runs)
        total_errors = sum(r.errors for r in runs)
        total_skipped = sum(r.skipped for r in runs)
        durations = [r.duration_ms for r in runs]

        recent = runs[-20:]

        return {
            "total_runs": len(runs),
            "total_resolved": total_resolved,
            "total_errors": total_errors,
            "total_skipped": total_skipped,
            "avg_duration_ms": round(sum(durations) / len(durations), 1),
            "max_duration_ms": round(max(durations), 1),
            "last_run_at": runs[-1].timestamp,
            "recent_runs": [
                {
                    "timestamp": r.timestamp,
                    "resolved": r.resolved,
                    "errors": r.errors,
                    "skipped": r.skipped,
                    "duration_ms": round(r.duration_ms, 1),
                }
                for r in recent
            ],
        }

    def get_error_log(self, limit: int = 50) -> list[dict]:
        """Return recent errors, newest first."""
        with self._lock:
            errors = list(self._errors)
        return [
            {
                "timestamp": e.timestamp,
                "component": e.component,
                "message": e.message,
            }
            for e in errors[-limit:]
        ][::-1]

    def get_summary(self) -> dict:
        """High-level summary for the dashboard header."""
        with self._lock:
            loop_iters = self._loop_iterations
            runs = list(self._resolver_runs)
            errors = list(self._errors)

        one_hour_ago = time.time() - 3600
        recent_errors = sum(1 for e in errors if e.timestamp > one_hour_ago)

        last_run = runs[-1] if runs else None

        return {
            "uptime_seconds": round(self.uptime_seconds),
            "loop_iterations": loop_iters,
            "total_errors": len(errors),
            "errors_last_hour": recent_errors,
            "last_resolver_run": {
                "timestamp": last_run.timestamp,
                "resolved": last_run.resolved,
                "errors": last_run.errors,
                "duration_ms": round(last_run.duration_ms, 1),
            }
            if last_run
            else None,
        }


# Global singleton
collector = MetricsCollector()
