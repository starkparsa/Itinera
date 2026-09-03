"""Raw Pexels API wrapper -- free, unlike google_places_client.py, but same
kill-switch/never-raises shape as the rest of this clients/ package.

PEXELS_API_KEY's presence *is* the kill switch (PEXELS_API_ENABLED), same
convention as GOOGLE_PLACES_API_KEY/GROQ_API_KEY -- unset it and
pexels_service.get_or_refresh_trip_photo no-ops immediately, no network
call, no code path change needed elsewhere. Trip.photo_url just stays
null forever and the frontend falls back to its flat color banner.

Caching: functools.lru_cache on search_photo -- a destination's
representative photo doesn't change from one search to the next, same
reasoning as google_places_client.text_search/place_details. Pexels' free
tier is 200 requests/hour, 20,000/month (confirmed live against their
docs) -- caching in-process, plus pexels_service.py's own
"only fetch once, ever, per trip" policy on top of this, keeps real usage
far under that even for a busy dev session.
"""
import functools
import os

import requests

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PEXELS_API_ENABLED = bool(PEXELS_API_KEY)

_BASE_URL = "https://api.pexels.com/v1"
_TIMEOUT = 10


@functools.lru_cache(maxsize=256)
def search_photo(query: str) -> dict | None:
    """Free-text query (typically a destination name) -> the top matching
    photo's url + photographer attribution, or None if nothing matched or
    the request failed. Pexels' own usage guidelines ask for photographer
    credit whenever a photo is shown -- `photographer`/`photographer_url`
    are carried through specifically so the frontend can display it, not
    just the bare image."""
    try:
        resp = requests.get(
            f"{_BASE_URL}/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos") or []
    except Exception:
        return None

    if not photos:
        return None
    photo = photos[0]
    return {
        "url": photo.get("src", {}).get("large"),
        "photographer": photo.get("photographer"),
        "photographer_url": photo.get("photographer_url"),
    }
