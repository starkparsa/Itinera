"""Raw Google Places API (New) wrapper -- billed, unlike wikipedia_client.py
and weather_service.py, so it needs its own kill switch and its own cost
discipline. Same "auth-free-of-LLM-concerns, never raises, None/falsy on a
miss" shape as wikipedia_client.py/weather_service.py's raw layer, just not
auth-free itself (needs GOOGLE_PLACES_API_KEY).

GOOGLE_PLACES_API_KEY's presence *is* the kill switch (PLACES_API_ENABLED),
same convention as GROQ_API_KEY -- unset it and every function that would
need it (tools.get_place_details/find_nearby_places) returns an {"error":
...} immediately, no network call, no code path change needed elsewhere.

Field masks (X-Goog-FieldMask) are kept as narrow as each call actually
needs -- Places API (New) bills per requested field tier ("SKU"), so this
is a real cost lever, not just tidy code (see tools.py's get_place_details
for how "brief" vs "detailed" map to different masks).

Caching: functools.lru_cache on text_search/place_details (a place's
identity/description doesn't change fast, same reasoning as
wikipedia_client.py). Deliberately NOT applied to nearby_search -- "what's
open near me right now" is exactly the kind of query where a stale cached
list (a place that closed, one that just opened) is more likely to
visibly mislead a user than Wikipedia's static content ever would; this
one call type accepts the small extra request/cost for freshness. Don't
"fix" this into consistency with the other two without re-reading why.
"""
import functools
import os

import requests

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
PLACES_API_ENABLED = bool(GOOGLE_PLACES_API_KEY)

_BASE_URL = "https://places.googleapis.com/v1"
_TIMEOUT = 10

_TEXT_SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.rating,"
    "places.priceLevel,places.types,places.location"
)
_PLACE_DETAILS_BRIEF_FIELD_MASK = (
    "id,displayName,formattedAddress,rating,priceLevel,types,currentOpeningHours.openNow"
)
_PLACE_DETAILS_DETAILED_FIELD_MASK = (
    _PLACE_DETAILS_BRIEF_FIELD_MASK
    + ",editorialSummary,generativeSummary,websiteUri,internationalPhoneNumber"
)
_NEARBY_SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.rating,"
    "places.priceLevel,places.currentOpeningHours.openNow"
)


def _headers(field_mask: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": field_mask,
    }


@functools.lru_cache(maxsize=256)
def text_search(query: str) -> dict | None:
    """Free-text query -> the top matching place's raw fields (id,
    displayName, formattedAddress, rating, priceLevel, types, location),
    or None if nothing matched or the request failed. The Places
    equivalent of wikipedia_client.resolve_title, but returns the fields
    themselves (already fetched in the same call) rather than just a title
    to resolve further. `location` (lat/lng) is included specifically so
    tools.find_nearby_places can geocode a landmark-level anchor (e.g.
    "the Louvre") that weather_service.geocode's city-name-oriented
    Open-Meteo geocoder can't resolve on its own -- see that function's
    docstring."""
    try:
        resp = requests.post(
            f"{_BASE_URL}/places:searchText",
            headers=_headers(_TEXT_SEARCH_FIELD_MASK),
            json={"textQuery": query},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        places = resp.json().get("places") or []
    except Exception:
        return None

    return places[0] if places else None


@functools.lru_cache(maxsize=256)
def place_details(place_id: str, detail: str = "brief") -> dict | None:
    """place_id (from text_search) -> a fuller raw field set, sized by
    detail ("brief"/"detailed" -- anything else treated as "brief"). None
    if the place_id is invalid or the request failed."""
    field_mask = (
        _PLACE_DETAILS_DETAILED_FIELD_MASK if detail == "detailed" else _PLACE_DETAILS_BRIEF_FIELD_MASK
    )
    try:
        resp = requests.get(
            f"{_BASE_URL}/places/{place_id}",
            headers=_headers(field_mask),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def nearby_search(lat: float, lng: float, place_type: str, radius_m: int = 1500) -> list[dict]:
    """Places of `place_type` (a Places API "included type", e.g.
    "restaurant", "cafe", "tourist_attraction") within radius_m of
    (lat, lng), capped at 5 results -- capping cost and prompt size at the
    source rather than trimming a larger response afterward. [] on any
    failure or when nothing is found (never None -- callers can iterate
    the result directly without a None-check)."""
    try:
        resp = requests.post(
            f"{_BASE_URL}/places:searchNearby",
            headers=_headers(_NEARBY_SEARCH_FIELD_MASK),
            json={
                "includedTypes": [place_type],
                "maxResultCount": 5,
                "locationRestriction": {
                    "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}
                },
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("places") or []
    except Exception:
        return []
