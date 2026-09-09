"""Raw Google Routes API wrapper (Compute Routes) -- billed, same
kill-switch/cost discipline as google_places_client.py. Reuses the same
billing-enabled Google Cloud project/API key as Places
(GOOGLE_PLACES_API_KEY) -- Routes API is a sibling product under the same
Google Maps Platform project, no separate credential needed, though the
Routes API itself must be separately enabled on that project in Google
Cloud Console (a Places-enabled key does not automatically cover it).

GOOGLE_PLACES_API_KEY's presence is this client's kill switch too
(ROUTES_API_ENABLED) -- same convention as every other billed
integration in this app (GROQ_API_KEY, PLACES_API_ENABLED).

Field mask kept to the absolute minimum (duration + distance only) -- the
Routes API bills by response field tier ("SKU"), and this app only ever
needs travel time/distance for pacing decisions, never turn-by-turn
directions (explicitly out of scope, see decisions.md's Maps/routing
entry). This keeps every call in the cheapest ("Essentials") pricing
tier -- verified live 2026-09-09: 10,000 free monthly events, then
$5.00/1,000 after.

No caching here (unlike google_places_client.py's lru_cache on
text_search/place_details) -- a specific origin/destination/mode triple
is unlikely to repeat often enough within one process's lifetime to be
worth it, and travel time (unlike a place's identity) is at least
theoretically time-varying (traffic), so a permanent in-memory cache
would be the wrong default here.
"""
import os

import requests

# Deliberately the same env var as google_places_client.py, not a new one
# -- see this module's docstring for why (same project, sibling API).
GOOGLE_ROUTES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
ROUTES_API_ENABLED = bool(GOOGLE_ROUTES_API_KEY)

_COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_TIMEOUT = 10
_FIELD_MASK = "routes.duration,routes.distanceMeters"

VALID_TRAVEL_MODES = ("DRIVE", "WALK", "BICYCLE", "TRANSIT")


def compute_route(origin: str, destination: str, travel_mode: str = "DRIVE") -> dict | None:
    """origin/destination as free-text addresses or place names -- the
    Routes API resolves them itself, no separate geocoding call needed
    (unlike find_nearby_places, which has to geocode `near` itself before
    calling Places' nearby search). travel_mode must already be one of
    VALID_TRAVEL_MODES; callers (tools.compute_travel_time) are
    responsible for normalizing/validating before calling this.

    Returns {"duration_seconds", "distance_meters"} on success, or None
    on any failure -- invalid/unreachable addresses, no route found
    between them, or a request error.
    """
    try:
        resp = requests.post(
            _COMPUTE_ROUTES_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_ROUTES_API_KEY,
                "X-Goog-FieldMask": _FIELD_MASK,
            },
            json={
                "origin": {"address": origin},
                "destination": {"address": destination},
                "travelMode": travel_mode,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        routes = resp.json().get("routes") or []
    except Exception:
        return None

    if not routes:
        return None

    route = routes[0]
    duration_raw = route.get("duration")  # Google's shape: a string like "1234s"
    distance_meters = route.get("distanceMeters")
    if duration_raw is None or distance_meters is None:
        return None

    try:
        duration_seconds = int(str(duration_raw).rstrip("s"))
    except ValueError:
        return None

    return {"duration_seconds": duration_seconds, "distance_meters": distance_meters}
