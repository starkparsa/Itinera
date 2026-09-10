"""Deterministic, art-free passport stamp styling. A trip's stamp accent
color is derived from its destination string alone -- same city always
stamps the same way, no per-city art asset or lookup table to maintain,
keeping this inside the $0 budget (CLAUDE.md constraint).

Also owns stamp deduplication and completion status -- both pure
functions of already-fetched Trip data, same "no DB access, trivially
testable" shape as accent_for_destination below. Scoped to Your Trips'
gamification display only; deliberately does NOT touch
stats_service.compute_trip_stats or gamification_service's
trip_count/XP/achievement counting -- a real duplicate GET/regenerate
still counted as a real trip planned before this fix, and changing that
is a separate decision this fix doesn't make.
"""
import hashlib
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import models

# A small fixed palette of existing Dusk City-adjacent hues (see
# docs/design-references.md's palette research) -- not arbitrary hex
# values, so a stamp always reads as "this app's colors," not a clashing
# one-off. Deliberately short; more variety isn't worth a maintained list.
STAMP_PALETTE = [
    "indigo", "copper", "teal", "amber", "rose", "violet", "emerald", "sky",
]


def accent_for_destination(destination: str) -> str:
    """One of STAMP_PALETTE's names, chosen deterministically from
    `destination` -- the same destination string always maps to the same
    color, with no state stored anywhere."""
    if not destination:
        return STAMP_PALETTE[0]
    digest = hashlib.md5(destination.encode("utf-8")).hexdigest()
    return STAMP_PALETTE[int(digest, 16) % len(STAMP_PALETTE)]


def is_trip_completed(start_date: date | None, total_days: int) -> bool:
    """A trip only ever reads as completed when there's a real date to
    prove it -- no start_date (or no itinerary days at all) always reads
    as still in progress, the same "no data beats a wrong answer"
    default this app already applies to weather/place context
    (principle #7) rather than guessing a trip is done just because it
    looks old."""
    if start_date is None or total_days < 1:
        return False
    trip_end_date = start_date + timedelta(days=total_days - 1)
    return date.today() > trip_end_date


def deduplicate_stamps(trips: list["models.Trip"]) -> list["models.Trip"]:
    """Collapses trips that share both a destination AND a real
    start_date into a single stamp -- the same trip replanned/regenerated
    (or a test/demo artifact), not two genuinely separate visits. Keeps
    the first occurrence in `trips`' own order (callers pass these
    ordered by created_at, so that's the earliest).

    A trip with no start_date is NEVER collapsed with anything else,
    including another dateless trip to the same destination -- with no
    date to compare, there's no way to tell "the same trip asked for
    twice" from "two separate trips to the same city" apart, and
    guessing would violate the same principle #7 discipline
    is_trip_completed above follows. Destination matching is
    case/whitespace-insensitive (`"Miami"` and `" miami "` are the same
    place), matching how a human would read two stamps as duplicates.
    """
    seen_keys: set[tuple[str, date]] = set()
    result: list[models.Trip] = []
    for trip in trips:
        if trip.start_date is None:
            result.append(trip)
            continue
        key = (trip.destination.strip().lower(), trip.start_date)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        result.append(trip)
    return result
