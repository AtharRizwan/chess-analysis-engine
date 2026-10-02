"""Clock facts: moves played too fast at critical moments, and mistakes in time trouble."""

from __future__ import annotations

from chess_analysis_engine.models import ClockInfo

RUSHED_SECONDS = 3.0
RUSHED_SHARE = 0.02  # or 2% of the starting clock, whichever is larger
TIME_TROUBLE_SHARE = 0.10


def clock_notes(clock: ClockInfo | None, base_seconds: float | None) -> list[tuple[str, dict]]:
    """("rushed" | "time_trouble", details) for a costly move."""
    if clock is None:
        return []
    notes: list[tuple[str, dict]] = []
    if clock.spent is not None:
        limit = max(RUSHED_SECONDS, RUSHED_SHARE * base_seconds) if base_seconds else RUSHED_SECONDS
        if clock.spent <= limit:
            notes.append(("rushed", {"spent": round(clock.spent, 1)}))
    if clock.remaining is not None and base_seconds and clock.remaining <= TIME_TROUBLE_SHARE * base_seconds:
        notes.append(("time_trouble", {"remaining": round(clock.remaining, 1)}))
    return notes
