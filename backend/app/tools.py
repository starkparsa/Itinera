"""Tool implementations the agent can call.

Currency conversion uses the free, no-key Frankfurter API. A weather tool
(OpenWeather) used to live here too -- removed after it proved unreliable
in practice; see CLAUDE.md's decision log. convert_currency isn't actively
reachable right now either -- it's still gated behind agent_service.py's
AGENT_TOOL_CALLING_ENABLED, paused as a product decision (see that
module's docstring).

THREE place tools exist now, split by what they're actually good at
(2026-09-01 -- see CLAUDE.md's decision log for the full rationale):
  - get_place_context (Wikipedia, free): history, cultural significance --
    "why is this place known for X." Static-ish content, fine to cache
    indefinitely.
  - get_place_details (Google Places, billed): current/practical facts --
    rating, price level, opening hours, category. Genuinely time-sensitive.
  - find_nearby_places (Google Places, billed): recommendations near a
    location -- a capability Wikipedia has no equivalent of at all.
All three are reached through the SAME two loops
(agent_service.answer_question_with_tools for conversational Q&A/tour-guide
use, and agent_service.gather_place_context_for_itinerary for
itinerary-planning background) -- see agent_service.py's module docstring
for why loops stay split by caching semantics, not by which tool they
expose. The two Places-backed tools have their own cost-control mechanism
distinct from a loop-level flag: GOOGLE_PLACES_API_KEY's presence (checked
via google_places_client.PLACES_API_ENABLED) is itself the kill switch --
unset it and both functions return {"error": ...} immediately, no network
call, so Wikipedia-only behavior is unaffected whether or not a Places key
is configured.

TOOL_SCHEMAS is in Gemini's function-calling shape (google.genai.types) as
of the Gemini migration -- previously Ollama's dict-list shape.
"""
import requests
from google.genai import types

from . import weather_service
from .clients import google_places_client, wikipedia_client

_BRIEF_CHAR_CAP = 320  # enforced even if Wikipedia's own extract runs long,
                        # so "brief" stays genuinely brief regardless of topic
_DETAILED_CHAR_CAP = 6000  # raised from 2000, 2026-08-29, for real tour-guide
                            # depth -- most landmark-level Wikipedia extracts
                            # fit whole under this; still bounded, not
                            # unbounded, so a genuinely huge article (a whole
                            # country, a major city) doesn't blow the prompt
                            # budget on one tool call


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Free currency conversion via the Frankfurter API (ECB rates, no API key)."""
    resp = requests.get(
        "https://api.frankfurter.app/latest",
        params={"amount": amount, "from": from_currency.upper(), "to": to_currency.upper()},
        timeout=15,
    ).json()

    converted = resp.get("rates", {}).get(to_currency.upper())
    if converted is None:
        return {"error": f"Could not convert {from_currency} to {to_currency}"}

    return {
        "amount": amount,
        "from": from_currency.upper(),
        "to": to_currency.upper(),
        "converted": converted,
    }


def _trim_to_cap(text: str, cap: int) -> str:
    """Deterministic text-shaping, not an LLM decision -- same "don't leave
    this to chance" discipline as calendar_export.py's time-of-day
    heuristic. Cuts at the last sentence boundary at or before `cap` when
    one exists, otherwise falls back to a hard word-boundary cut so a
    "brief" reply never trails off mid-word."""
    if len(text) <= cap:
        return text

    truncated = text[:cap]
    last_period = truncated.rfind(". ")
    if last_period != -1:
        return truncated[: last_period + 1]

    last_space = truncated.rfind(" ")
    return (truncated[:last_space] if last_space != -1 else truncated) + "..."


def get_place_context(place_name: str, near: str | None = None, detail: str = "brief") -> dict:
    """Give the LLM just enough real, grounded context about a named place
    to help plan or answer questions about a trip -- never a full synopsis
    unless explicitly asked (principle #7: ground it in real data, never
    invent it; and don't dump an encyclopedia entry when a sentence will
    do). 'brief' (default): a 1-3 sentence overview, sourced from
    Wikipedia's own already-short lead summary. 'detailed': a fuller
    overview (still capped, never unbounded), sourced from the full
    article extract -- only meant to be requested when the user explicitly
    wants more (tour-guide-style history/background).

    Returns {"place","summary","detail"} on success, or {"error": ...} if
    no matching Wikipedia page could be found or it has no usable text.
    """
    title = wikipedia_client.resolve_title(place_name, near=near)
    if title is None:
        return {"error": f"Could not find a Wikipedia page for '{place_name}'"}

    if detail == "detailed":
        text = wikipedia_client.get_full_extract(title)
        cap = _DETAILED_CHAR_CAP
    else:
        detail = "brief"  # normalize any unrecognized value to the safe default
        text = wikipedia_client.get_summary(title)
        cap = _BRIEF_CHAR_CAP

    if not text:
        return {"error": f"No summary available for '{title}'"}

    return {"place": title, "summary": _trim_to_cap(text, cap), "detail": detail}


def get_place_details(place_name: str, near: str | None = None, detail: str = "brief") -> dict:
    """Give the LLM current, practical facts about a named place -- rating,
    price level, category, whether it's open right now -- the complement
    to get_place_context's historical framing. Sourced from Google Places
    (billed; see google_places_client.py's module docstring for the cost
    controls). 'detailed' additionally includes an editorial/generative
    summary, website, and phone number when Google has them.

    Returns {"place","address","rating","price_level","types","open_now","summary"}
    on success (summary only populated for detail="detailed", and only if
    Google supplied one), or {"error": ...} if the Places integration
    isn't configured or no matching place could be found.
    """
    if not google_places_client.PLACES_API_ENABLED:
        return {"error": "Google Places lookup is not configured"}

    query = f"{place_name} {near}" if near else place_name
    match = google_places_client.text_search(query)
    if match is None:
        return {"error": f"Could not find a Google Places match for '{place_name}'"}

    detail = detail if detail == "detailed" else "brief"  # normalize, same as get_place_context
    place_id = match.get("id")
    fuller = google_places_client.place_details(place_id, detail=detail) if place_id else None
    fuller = fuller or match  # fall back to the text_search fields if the details lookup failed

    summary = None
    if detail == "detailed":
        raw_summary = (fuller.get("editorialSummary") or {}).get("text") or (
            fuller.get("generativeSummary") or {}
        ).get("overview", {}).get("text")
        summary = _trim_to_cap(raw_summary, _DETAILED_CHAR_CAP) if raw_summary else None

    return {
        "place": (fuller.get("displayName") or {}).get("text") or place_name,
        "address": fuller.get("formattedAddress"),
        "rating": fuller.get("rating"),
        "price_level": fuller.get("priceLevel"),
        "types": fuller.get("types"),
        "open_now": (fuller.get("currentOpeningHours") or {}).get("openNow"),
        "summary": summary,
    }


def _geocode_for_places(near: str) -> tuple[float, float] | None:
    """Resolve `near` to (lat, lng) for find_nearby_places, trying the
    existing free Open-Meteo geocoder first (weather_service.geocode) and
    falling back to Google Places' own text_search when that fails.

    Live-verified need for the fallback (2026-09-01): Open-Meteo's
    geocoder is city/place-name oriented and reliably fails on a
    landmark-level `near` (e.g. "the Louvre", "1st arrondissement Paris")
    -- confirmed live, it returned no match for several such phrasings.
    Before this fallback existed, that failure surfaced as the *model*
    retrying find_nearby_places several times with progressively broader
    guesses at `near`, burning multiple real Gemini + geocoding calls and,
    in one observed run, exhausting MAX_TOOL_ROUNDS before ever reaching a
    successful call -- the tool worked, but the round budget didn't
    survive the model's guessing. Resolving this deterministically in one
    place, rather than leaving it to repeated LLM guesses, is the same
    "don't leave to chance what code can just handle" discipline principle
    #6 already applies to date arithmetic.

    text_search is a billed Places call, so this fallback path costs real
    money -- but only on the (uncommon) case where the free geocoder
    already failed, and it's one bounded call, not a loop.
    """
    coords = weather_service.geocode(near)
    if coords is not None:
        return coords

    if not google_places_client.PLACES_API_ENABLED:
        return None
    match = google_places_client.text_search(near)
    location = (match or {}).get("location")
    if not location:
        return None
    return location.get("latitude"), location.get("longitude")


def find_nearby_places(place_type: str, near: str, limit: int = 5) -> dict:
    """Recommend up to `limit` real places of `place_type` (e.g.
    "restaurant", "cafe", "tourist_attraction" -- a Google Places
    "included type") near a named location -- a capability Wikipedia has
    no equivalent of. Sourced from Google Places (billed).

    Returns {"results": [{"name","rating","address","price_level","open_now"}, ...]}
    on success (possibly an empty list if nothing matched), or
    {"error": ...} if the Places integration isn't configured or `near`
    couldn't be resolved to a location at all.
    """
    if not google_places_client.PLACES_API_ENABLED:
        return {"error": "Google Places lookup is not configured"}

    coords = _geocode_for_places(near)
    if coords is None:
        return {"error": f"Could not resolve a location for '{near}'"}

    places = google_places_client.nearby_search(coords[0], coords[1], place_type)
    results = [
        {
            "name": (p.get("displayName") or {}).get("text"),
            "rating": p.get("rating"),
            "address": p.get("formattedAddress"),
            "price_level": p.get("priceLevel"),
            "open_now": (p.get("currentOpeningHours") or {}).get("openNow"),
        }
        for p in places[: max(0, limit)]
    ]
    return {"results": results}


# Gemini-shaped tool schema (google.genai.types.Tool / FunctionDeclaration),
# passed to GenerateContentConfig(tools=[...]) in agent_service.py.
#
# Split into per-loop schemas, not just one merged list: agent_service.py
# runs THREE separate tool-calling loops (gather_trip_context for currency,
# answer_question_with_tools for conversational place-context,
# gather_place_context_for_itinerary for itinerary-planning place-context)
# with different caching semantics and different kill switches
# (AGENT_TOOL_CALLING_ENABLED / QA_TOOL_CALLING_ENABLED /
# PLANNING_TOOL_CALLING_ENABLED). If every tool were advertised to every
# loop via one shared schema, flipping one loop's flag on would silently
# make another loop's tool reachable too, defeating its own pause/isolation.
# Each loop must only ever see the schema for the tool(s) it owns -- the
# two place-context loops happen to share the same underlying
# FunctionDeclaration object (get_place_context itself doesn't differ),
# they just each get their own types.Tool wrapper and their own flag.
_CONVERT_CURRENCY_DECLARATION = types.FunctionDeclaration(
    name="convert_currency",
    description="Convert an amount of money from one currency to another using current exchange rates.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount to convert"},
            "from_currency": {"type": "string", "description": "3-letter currency code, e.g. USD"},
            "to_currency": {"type": "string", "description": "3-letter currency code, e.g. EUR"},
        },
        "required": ["amount", "from_currency", "to_currency"],
    },
)

_GET_PLACE_CONTEXT_DECLARATION = types.FunctionDeclaration(
    name="get_place_context",
    description=(
        "Get a short overview of a named place (landmark, neighborhood, "
        "city) to help plan or answer questions about a trip. Defaults "
        "to a brief 1-3 sentence overview -- only pass detail='detailed' "
        "when the user explicitly wants a fuller history/background "
        "(e.g. asking you to be a 'tour guide' or for 'the full history')."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "place_name": {"type": "string", "description": "Name of the place, e.g. 'Eiffel Tower'"},
            "near": {"type": "string", "description": "Optional city/region to disambiguate a common place name"},
            "detail": {
                "type": "string",
                "enum": ["brief", "detailed"],
                "description": "brief (default) unless the user explicitly wants more",
            },
        },
        "required": ["place_name"],
    },
)

_GET_PLACE_DETAILS_DECLARATION = types.FunctionDeclaration(
    name="get_place_details",
    description=(
        "Get CURRENT, practical facts about a named place (landmark, "
        "restaurant, museum, etc.) -- rating, price level, category, and "
        "whether it's open right now. Use this for questions about a "
        "place's present-day status or quality, not its history (use "
        "get_place_context for that instead). Costs real money per call, "
        "unlike get_place_context -- only call when the question actually "
        "needs current/practical data."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "place_name": {"type": "string", "description": "Name of the place, e.g. 'the Louvre'"},
            "near": {"type": "string", "description": "Optional city/region to disambiguate a common place name"},
            "detail": {
                "type": "string",
                "enum": ["brief", "detailed"],
                "description": "brief (default) unless the user explicitly wants more (adds a summary/website/phone)",
            },
        },
        "required": ["place_name"],
    },
)

_FIND_NEARBY_PLACES_DECLARATION = types.FunctionDeclaration(
    name="find_nearby_places",
    description=(
        "Recommend real, named places of a given type (e.g. 'restaurant', "
        "'cafe', 'tourist_attraction') near a location -- use this when "
        "the user wants a recommendation or list near somewhere, a "
        "capability Wikipedia has no equivalent of. Costs real money per "
        "call -- only call when the user is actually asking for a "
        "recommendation, not speculatively."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "place_type": {
                "type": "string",
                "description": "Google Places type, e.g. 'restaurant', 'cafe', 'tourist_attraction', 'museum'",
            },
            "near": {"type": "string", "description": "City, neighborhood, or landmark to search near"},
            "limit": {"type": "integer", "description": "Max results to return, default 5"},
        },
        "required": ["place_type", "near"],
    },
)

# Used by agent_service.gather_trip_context (currency only).
CURRENCY_TOOL_SCHEMAS = types.Tool(function_declarations=[_CONVERT_CURRENCY_DECLARATION])

_PLACE_TOOL_DECLARATIONS = [
    _GET_PLACE_CONTEXT_DECLARATION,
    _GET_PLACE_DETAILS_DECLARATION,
    _FIND_NEARBY_PLACES_DECLARATION,
]

# Used by agent_service.answer_question_with_tools (place-context only).
QA_TOOL_SCHEMAS = types.Tool(function_declarations=_PLACE_TOOL_DECLARATIONS)

# Used by agent_service.gather_place_context_for_itinerary (place-context
# only, itinerary-planning use rather than conversational Q&A -- own
# types.Tool wrapper so it can be independently kill-switched via
# PLANNING_TOOL_CALLING_ENABLED without touching QA_TOOL_CALLING_ENABLED).
PLANNING_TOOL_SCHEMAS = types.Tool(function_declarations=_PLACE_TOOL_DECLARATIONS)

# Everything this module can do, for tests/introspection -- never pass this
# combined list into a live GenerateContentConfig(tools=[...]) call, or a
# loop's kill switch stops actually isolating its tool.
TOOL_SCHEMAS = types.Tool(function_declarations=[
    _CONVERT_CURRENCY_DECLARATION,
    *_PLACE_TOOL_DECLARATIONS,
])

TOOL_FUNCTIONS = {
    "convert_currency": convert_currency,
    "get_place_context": get_place_context,
    "get_place_details": get_place_details,
    "find_nearby_places": find_nearby_places,
}
