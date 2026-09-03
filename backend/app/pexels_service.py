"""Trip-photo cache layer -- mirrors weather_service.py's
"read cached, refresh only when needed, caller commits" shape, but with a
simpler policy than weather's 3-hour TTL: a destination's representative
photo doesn't go stale the way a forecast does, so this fetches at most
once per trip, ever, rather than checking freshness on every read.

PEXELS_API_ENABLED is the kill switch (see clients/pexels_client.py) --
with no key set, get_or_refresh_trip_photo returns None immediately, no
network call, and Trip.photo_url simply stays null forever. The frontend
(TripCard.tsx) falls back to a flat color banner in that case -- never a
broken image, never an invented one.
"""
from datetime import datetime

from . import models
from .clients import pexels_client


# Tried first, in order -- a night skyline shot is what the user actually
# wants for every trip card; the plain destination name is the fallback
# ONLY for a destination Pexels genuinely has no skyline-style photo for
# (a small town, a national park, a beach with no city behind it), never a
# "prefer variety" choice. We can't ask Pexels whether a result is
# "really" a skyline -- there's no semantic/vision check here, only
# whether the search returns anything at all -- so "not possible" is
# judged the same honest way every other empty-result case in this
# codebase is: zero results back, not a quality judgment we're not
# equipped to make.
_PHOTO_QUERY_PRIORITY = ["{destination} city skyline at night", "{destination}"]


def get_or_refresh_trip_photo(trip: "models.Trip") -> dict | None:
    """Returns `{"url", "credit"}` for a trip's representative photo,
    fetching it from Pexels only the first time (`trip.photo_url is
    None`) and reading the cached value on every call after that. Mutates
    `trip.photo_url`/`photo_credit`/`photo_fetched_at` in place on a fresh
    fetch -- the caller owns the DB session and must commit, same
    contract as weather_service.get_or_refresh_trip_weather.

    Tries each query in _PHOTO_QUERY_PRIORITY in order, keeping the first
    one that returns a real result -- a night skyline first, the bare
    destination name only as a fallback (see that constant's comment).

    None if Pexels isn't configured, every query in the priority list came
    back empty, or the request failed -- never a placeholder or
    fabricated URL.
    """
    if trip.photo_url is not None:
        return {"url": trip.photo_url, "credit": trip.photo_credit}

    if not pexels_client.PEXELS_API_ENABLED:
        return None

    photo = None
    for query_template in _PHOTO_QUERY_PRIORITY:
        photo = pexels_client.search_photo(query_template.format(destination=trip.destination))
        if photo and photo.get("url"):
            break
    if not photo or not photo.get("url"):
        return None

    trip.photo_url = photo["url"]
    trip.photo_credit = photo.get("photographer")
    trip.photo_fetched_at = datetime.utcnow()
    return {"url": trip.photo_url, "credit": trip.photo_credit}
