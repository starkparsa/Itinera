"""Derives a Trip's list-view status (draft / upcoming / completed) in real
Python -- never guessed by the LLM, same "no date arithmetic in a prompt"
principle date_resolver.py already applies to resolving a start date in
the first place (CLAUDE.md architecture principle #6, extended here to
trip *status* rather than just the date itself).

Trip has no `status` column and no `end_date` column (see models.py) --
both are derived on read, not stored, so there's never a stale status sitting
in the database that a later edit (a rescheduled date, an itinerary that
grew a day) could silently leave wrong.
"""

from datetime import date, timedelta


def derive_status(start_date: date | None, day_count: int, today: date | None = None) -> str:
    """`today` is an injectable override (mirrors
    date_resolver.resolve_trip_start_date's `current_date` param) purely
    for deterministic tests -- real callers omit it and get `date.today()`.
    """
    if start_date is None:
        return "draft"

    today = today or date.today()
    # day_count is 1-indexed (day_number starts at 1), so a `day_count`-day
    # trip starting on start_date ends on start_date + (day_count - 1).
    # day_count of 0 (a trip with no itinerary items yet, shouldn't happen
    # in practice but isn't impossible mid-generation) is treated as a
    # single day so a same-day trip doesn't read as already over before it
    # exists.
    trip_end = start_date + timedelta(days=max(day_count, 1) - 1)
    if trip_end < today:
        return "completed"
    return "upcoming"
