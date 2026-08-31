"""Raw Wikipedia API wrapper -- free, no API key, no billing account, just a
proper User-Agent header (Wikimedia's own etiquette policy). No LLM concerns
here: this module only resolves a free-text place name to a real page and
fetches its text, the same "auth-free HTTP calls, never raises, None on a
miss" shape as weather_service.py's _geocode_result/geocode.

Split into three small functions rather than one combined call so
tools.py's get_place_context can pick brief vs. detailed independently of
resolving the title (principle #3: raw API wrapper vs. LLM-facing shaping
stay separate layers).

Caching: functools.lru_cache, not a TTL cache -- no new dependency, and
Wikipedia place facts don't meaningfully change within this app's process
lifetime, unlike weather_service's genuinely time-sensitive 3h TTL.
"""
import functools

import requests

USER_AGENT = "Itinera/1.0 (https://github.com/starkparsa/Itinera)"
_HEADERS = {"User-Agent": USER_AGENT}
_TIMEOUT = 10


@functools.lru_cache(maxsize=256)
def resolve_title(query: str, near: str | None = None) -> str | None:
    """Opensearch lookup: query (+ ' {near}' appended if given, to help
    disambiguate a common name like 'Louvre') -> the top matching canonical
    Wikipedia page title, or None if nothing matched or the request failed.

    Not a fuzzy-match guarantee -- a genuine typo can surface the right
    page below the top result (confirmed live: "eiffel towerr" placed
    "Eiffel Tower" 2nd, not 1st). Same known-gap category as
    weather_service's geocoder having no fuzzy-match fallback; not solved
    here either, not worth it without a real reported case.
    """
    search_term = f"{query} {near}" if near else query
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": search_term,
                "limit": 1,
                "namespace": 0,
                "format": "json",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        ).json()
    except Exception:
        return None

    titles = resp[1] if len(resp) > 1 else []
    return titles[0] if titles else None


@functools.lru_cache(maxsize=256)
def get_summary(title: str) -> str | None:
    """REST page/summary/{title} -> the 'extract' field, Wikipedia's own
    already-brief lead-paragraph text (confirmed live: 2-4 sentences,
    ~180-650 chars depending on topic). None on a normal 404 (page exists
    per opensearch but has no summary, or a transient failure) -- not an
    exception, since a missing summary is an expected outcome here."""
    try:
        resp = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("extract") or None
    except Exception:
        return None


@functools.lru_cache(maxsize=256)
def get_full_extract(title: str) -> str | None:
    """Action API prop=extracts (exintro=0, explaintext=1) -> a much fuller
    plain-text extract than get_summary (confirmed live: 2000+ chars for a
    substantial article) -- the 'detailed' mode source. None if the page or
    its extract is unavailable."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": 0,
                "explaintext": 1,
                "titles": title,
                "format": "json",
                "formatversion": 2,
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        ).json()
    except Exception:
        return None

    pages = resp.get("query", {}).get("pages") or []
    if not pages:
        return None
    return pages[0].get("extract") or None
