"""Raw Ticketmaster Discovery API wrapper -- free (5,000 requests/day, no
card, confirmed live), same kill-switch/never-raises shape as the rest of
this clients/ package.

TICKETMASTER_API_KEY's presence *is* the kill switch
(TICKETMASTER_API_ENABLED), same convention as GOOGLE_PLACES_API_KEY/
GROQ_API_KEY -- unset it and tools.find_events returns an {"error": ...}
immediately, no network call.

Only the Consumer Key (the `apikey` query param on every Discovery API
read) is used here -- the Consumer Secret is for signed Commerce API
calls (checkout/booking), out of scope for this integration and never
read or stored.

Caching: functools.lru_cache on get_event (one specific event's core
identity -- date, venue -- is stable within a session, same reasoning as
google_places_client.place_details). Deliberately NOT applied to
search_events -- event listings go stale (sold out, rescheduled,
cancelled) in a way a cached list would visibly mislead a user on, the
same freshness-over-caching call google_places_client.nearby_search
already makes and documents.
"""
import functools
import os
from datetime import date

import requests

TICKETMASTER_API_KEY = os.getenv("TICKETMASTER_API_KEY")
TICKETMASTER_API_ENABLED = bool(TICKETMASTER_API_KEY)

_BASE_URL = "https://app.ticketmaster.com/discovery/v2"
_TIMEOUT = 10


def search_events(
    city: str, keyword: str | None = None, start_date: date | None = None,
    end_date: date | None = None, size: int = 5,
) -> list[dict]:
    """Events in `city` (optionally filtered by `keyword` -- the user's
    stated interest/genre, e.g. "jazz", "basketball") and optionally a
    date window. Returns the raw `_embedded.events` list from Ticketmaster
    (each a large, deeply nested dict -- tools.find_events is responsible
    for flattening), capped at `size`. [] on any failure or when nothing
    is found (never None -- callers iterate the result directly).

    `keyword` maps to Ticketmaster's `classificationName` query param, NOT
    its `keyword` param -- confirmed live during planning that `keyword`
    does plain full-text matching against event/team/venue *names*, which
    produces real false positives for exactly the kind of interest term
    this is meant to filter on (searching "jazz" as a `keyword` returned
    "Miami Heat vs. Utah Jazz", a basketball game, matched on the
    opposing team's name -- not an actual jazz show). `classificationName`
    matches against Ticketmaster's own segment/genre/subGenre taxonomy
    instead, confirmed live to return real genre-correct results for both
    a music genre ("jazz") and a sport ("basketball")."""
    params = {"apikey": TICKETMASTER_API_KEY, "city": city, "size": size}
    if keyword:
        params["classificationName"] = keyword
    if start_date:
        params["startDateTime"] = f"{start_date.isoformat()}T00:00:00Z"
    if end_date:
        params["endDateTime"] = f"{end_date.isoformat()}T23:59:59Z"

    try:
        resp = requests.get(f"{_BASE_URL}/events.json", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("_embedded", {}).get("events") or []
    except Exception:
        return []


@functools.lru_cache(maxsize=256)
def get_event(event_id: str) -> dict | None:
    """One event's full raw record by id -- used to re-confirm an
    event's authoritative date server-side before letting it drive a
    trip's start_date (see event_planning.py), rather than trusting
    whatever a tool result happened to carry from an earlier turn. None
    if the id is invalid or the request failed."""
    try:
        resp = requests.get(
            f"{_BASE_URL}/events/{event_id}.json",
            params={"apikey": TICKETMASTER_API_KEY},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None
