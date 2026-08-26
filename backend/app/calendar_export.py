"""Builds a downloadable .ics calendar file for a generated trip -- pure
formatting logic, no LLM call and no network call, same category as
date_resolver.py/weather_service.py. This is the backend half of build-order
item 3 (CLAUDE.md); PDF export is out of scope for now.

One VEVENT per ItineraryItem. Each item's real calendar date is computed as
`trip.start_date + (day_number - 1)` -- plain Python arithmetic, never LLM
reasoning (principle #6's discipline, even though no LLM is anywhere near
this module). Callers must check `trip.start_date is not None` before
calling build_trip_calendar(); this module assumes a resolved date, same
division of responsibility as weather_service's callers checking
trip.start_date first.

Deliberately floating local time, no TZID: there's no reliable
per-destination timezone available at this layer without a second geocode
call (weather_service's Open-Meteo request uses timezone=auto internally,
but that resolved value never surfaces here), and floating time is valid
RFC 5545 behavior for "9am in Lisbon" regardless of the importing calendar
app's own timezone.
"""
import re
from datetime import date, datetime, time, timedelta

from icalendar import Calendar, Event

from . import models

DEFAULT_EVENT_DURATION = timedelta(hours=2)  # items carry no explicit duration

# Keyword substring lookup, not an LLM call -- same style as
# streamlit_app.py::_weather_icon. Checked in this order (most specific
# first) so "late morning" resolves to 11:00 rather than being caught by
# the plainer "morning" check first.
TIME_KEYWORDS = [
    ("late morning", (11, 0)),
    ("early morning", (6, 0)),
    ("morning", (9, 0)),
    ("late afternoon", (16, 0)),
    ("afternoon", (14, 0)),
    ("midday", (12, 0)),
    ("noon", (12, 0)),
    ("late night", (22, 0)),
    ("night", (20, 0)),
    ("evening", (18, 0)),
]

_TIME_24H_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_TIME_12H_RE = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?m\.?\b", re.IGNORECASE)


def resolve_event_time(time_of_day: str | None) -> tuple[int, int] | None:
    """Recognizes a concrete clock time from a freeform time_of_day string
    (e.g. "14:00", "2pm", "morning"). Returns (hour, minute) in 24h clock,
    or None if nothing recognizable is there -- in which case the caller
    should emit an all-day event rather than guess a time. Public (not
    module-private) because google_calendar.py (Phase D) reuses this exact
    logic for live Calendar pushes -- one time-resolution rule, not two."""
    if not time_of_day:
        return None
    text = time_of_day.strip().lower()

    match = _TIME_24H_RE.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))

    match = _TIME_12H_RE.search(text)
    if match:
        hour = int(match.group(1)) % 12
        minute = int(match.group(2) or 0)
        if match.group(3) == "p":
            hour += 12
        return hour, minute

    for keyword, hour_minute in TIME_KEYWORDS:
        if keyword in text:
            return hour_minute

    return None


def ics_filename(destination: str) -> str:
    """"Paris, France" -> "paris-france-itinerary.ics" -- for Content-Disposition."""
    slug = re.sub(r"[^a-z0-9]+", "-", destination.lower()).strip("-") or "trip"
    return f"{slug}-itinerary.ics"


def build_trip_calendar(
    trip_id: int,
    destination: str,
    start_date: date,
    items: list["models.ItineraryItem"],
) -> bytes:
    """Builds a full RFC 5545 .ics calendar (UTF-8 bytes) with one VEVENT per
    itinerary item. Never raises on odd input (e.g. an empty item list still
    produces a valid, empty VCALENDAR) -- the 400 for "can't export yet" is
    the caller's job (missing start_date), not this function's."""
    cal = Calendar()
    cal.add("prodid", "-//AI Travel Planner//Itinerary Export//EN")
    cal.add("version", "2.0")

    dtstamp = datetime.utcnow()

    for item in items:
        day_date = start_date + timedelta(days=item.day_number - 1)
        event = Event()
        event.add("uid", f"trip-{trip_id}-item-{item.id}@ai-travel-planner.local")
        event.add("dtstamp", dtstamp)
        event.add("summary", item.activity)
        event.add("location", destination)
        if item.notes:
            event.add("description", item.notes)

        start_time = resolve_event_time(item.time_of_day)
        if start_time is not None:
            hour, minute = start_time
            dtstart = datetime.combine(day_date, time(hour, minute))
            event.add("dtstart", dtstart)
            event.add("dtend", dtstart + DEFAULT_EVENT_DURATION)
        else:
            # All-day event -- icalendar emits VALUE=DATE automatically when
            # given a date object instead of a datetime. RFC 5545 requires
            # an exclusive end date for all-day events.
            event.add("dtstart", day_date)
            event.add("dtend", day_date + timedelta(days=1))

        cal.add_component(event)

    return cal.to_ical()
