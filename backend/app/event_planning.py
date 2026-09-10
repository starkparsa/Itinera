"""Turns a real event's date into a trip's start_date -- in real Python,
never LLM arithmetic, the same discipline date_resolver.py already
applies to resolving a date from free text (CLAUDE.md architecture
principle #6, extended here from "text -> date" to "event -> date").

Deliberately a separate module from date_resolver.py, not folded into
it -- that module's whole contract is parsing free text into a date via
regex + dateutil; this is plain date arithmetic on an already-known,
already-verified event date, a genuinely different concern. Small and
isolated, same shape as trip_status.py.
"""
import re
from datetime import date, timedelta

# The user asked for "a day or 2" of settle-in time before the event --
# 2 is the default (more buffer, safer), a single constant to tune.
SETTLE_IN_DAYS = 2

# Matches PLANNING_TOOL_SYSTEM_PROMPT's exact required line
# ("COMMITTED_EVENT_ID: <id>") -- a fixed, deterministic marker the model
# is instructed to emit only when the request's own wording truly commits
# to a specific event, never for a browsing/interest-only question. A
# structured marker line, not fuzzy text matching, so detecting a
# commitment is exact and testable rather than a guess at the model's
# prose.
_COMMITTED_EVENT_ID_PATTERN = re.compile(r"^COMMITTED_EVENT_ID:\s*(\S+)\s*$", re.MULTILINE)

# Matches PLANNING_TOOL_SYSTEM_PROMPT's exact required line
# ("EVENT_NOT_FOUND: <what was searched>") -- the counterpart to
# COMMITTED_EVENT_ID for the case where the request's wording truly
# commits to a specific named event/artist, but find_events came back
# with nothing. Without this, a real "we looked and found nothing" fact
# was only ever mentioned somewhere inside the day-by-day itinerary
# prose (easy to miss, not something the frontend could surface as its
# own callout) -- this marker lets routers/trips.py turn it into a real,
# separately-rendered TripResponse.note (see TripView.tsx's Alert),
# instead of a burying it in one day's activity notes.
_EVENT_NOT_FOUND_PATTERN = re.compile(r"^EVENT_NOT_FOUND:\s*(.+?)\s*$", re.MULTILINE)


def extract_committed_event_id(summary_text: str) -> str | None:
    """Pulls the event id out of a planning-loop summary that committed to
    building the trip around a specific event, or None if it didn't --
    see PLANNING_TOOL_SYSTEM_PROMPT's "CRITICAL -- committing vs.
    browsing" instruction, which this pairs with."""
    match = _COMMITTED_EVENT_ID_PATTERN.search(summary_text or "")
    return match.group(1) if match else None


def extract_event_not_found(summary_text: str) -> str | None:
    """Pulls out what the traveler asked to build a trip around, when the
    request truly committed to it but find_events found nothing -- or
    None if that never happened (the common case: no commitment attempt,
    or one that succeeded). See PLANNING_TOOL_SYSTEM_PROMPT's
    "EVENT_NOT_FOUND:" instruction, which this pairs with."""
    match = _EVENT_NOT_FOUND_PATTERN.search(summary_text or "")
    return match.group(1) if match else None


def resolve_start_date_for_event(event_date: date, settle_in_days: int = SETTLE_IN_DAYS) -> date:
    """The trip's start_date when it's being built around `event_date` --
    `settle_in_days` before the event, never the event date itself, so
    there's real time to arrive and settle in first."""
    return event_date - timedelta(days=settle_in_days)
