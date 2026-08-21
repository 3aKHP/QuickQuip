"""Shared scheduling helpers for adapter plugins: cron parsing and manual-trigger cooldown.

Package-private module (see _forward.py for the same convention). Cooldown state
is owned by each consumer — every plugin/report kind keeps its own dict instance;
only the mechanism is shared here.
"""
from __future__ import annotations

from time import time

MANUAL_COOLDOWN_SECONDS = 60


def cron_to_hhmm(cron_expr: str) -> str:
    """Convert a 5-field cron expression to an HH:MM display string.

    Returns the first hour:minute that matches (handles simple numeric fields).
    Falls back to the raw expression if fields are not plain integers.
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr
    minute_field, hour_field = parts[0], parts[1]
    try:
        return f"{int(hour_field):02d}:{int(minute_field):02d}"
    except ValueError:
        return f"{hour_field}:{minute_field}"


def parse_cron(cron_expr: str, *, fallback_hour: str) -> dict[str, str]:
    parts = cron_expr.split()
    if len(parts) != 5:
        return {"minute": "0", "hour": fallback_hour, "day": "*", "month": "*", "day_of_week": "*"}
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def on_cooldown(
    last_trigger: dict[str, float],
    group_id: int | str,
    cooldown_seconds: float = MANUAL_COOLDOWN_SECONDS,
) -> bool:
    last = last_trigger.get(str(group_id))
    return last is not None and time() - last < cooldown_seconds


def mark_triggered(last_trigger: dict[str, float], group_id: int | str) -> None:
    # asyncio is single-threaded; the check-then-mark sequence at call sites has
    # no await in between, so it is atomically safe within the event loop.
    last_trigger[str(group_id)] = time()
