"""Real, bookable events (Ticketmaster, via tools.find_events) for a trip's
Trip Hub card. Deliberately NOT routed through the Gemini tool-calling
loop the way conversational event lookups are -- like weather_service.py,
"does this trip get an events list" is never a judgment call the model
makes, it's the same fetch for every trip with a resolved destination and
start date. Structurally mirrors weather_service.py's cache contract
(CLAUDE.md principles #4/#5): read the cached `Trip.events_json` when
fresh, only call out again once it's stale, and never raise -- any miss
(no destination, Ticketmaster not configured, no matches, a request
failure) just means "no events shown" for that trip, never a fabricated
list (principle #7).
"""
import json
from datetime import date, datetime, timedelta

from . import models, tools

# Shorter-lived than weather's 3h TTL would be wrong for the wrong reason
# (events don't need MORE freshness than weather) but longer is also wrong:
# ticket availability/sellouts/cancellations change on their own schedule,
# and Ticketmaster's free tier (5,000 req/day) comfortably supports
# refreshing every few hours per trip.
CACHE_TTL = timedelta(hours=6)


def get_or_refresh_trip_events(trip: "models.Trip") -> list[dict]:
    """Returns a trip's event listings, reading the cached
    `Trip.events_json` when it's fresh and only calling out to Ticketmaster
    again when it's missing or stale. Mutates `trip.events_json`/
    `events_fetched_at` in place on a fresh fetch -- caller owns the DB
    session and must commit (same contract as
    weather_service.get_or_refresh_trip_weather).

    Returns [] (never the tool's raw {"error": ...} string) when there's no
    destination, Ticketmaster isn't configured, or find_events finds
    nothing/fails -- "no events" is never distinguished from "we couldn't
    check," matching the "no data beats invented data" posture used
    everywhere else in this module's family.
    """
    if not trip.destination:
        return []

    is_stale = (
        trip.events_fetched_at is None
        or datetime.utcnow() - trip.events_fetched_at > CACHE_TTL
    )
    if not is_stale and trip.events_json:
        return json.loads(trip.events_json)

    end_date = _trip_end_date(trip)
    result = tools.find_events(
        city=trip.destination,
        start_date=trip.start_date.isoformat() if trip.start_date else None,
        end_date=end_date.isoformat() if end_date else None,
    )
    events_out = result.get("results", []) if "error" not in result else []

    trip.events_json = json.dumps(events_out)
    trip.events_fetched_at = datetime.utcnow()
    return events_out


def _trip_end_date(trip: "models.Trip") -> date | None:
    """The trip's last day, for find_events' end_date window -- mirrors
    weather's "max(item.day_number for item in items)" day-count logic, but
    events need an actual calendar date rather than a day offset. None if
    there's no start_date or no itinerary items yet, in which case
    find_events is called with no end bound (an open-ended window from
    start_date, or entirely undated if start_date is also unset)."""
    if not trip.start_date or not trip.items:
        return None
    max_day_number = max(item.day_number for item in trip.items)
    return trip.start_date + timedelta(days=max_day_number - 1)
