"""Real-time per-day weather forecast via Open-Meteo -- free, no API key,
no card, non-commercial use (see CLAUDE.md decision log). Deliberately NOT
in tools.py / not registered as a Gemini-callable tool: unlike currency
conversion, "does this trip get a forecast" is never a judgment call the
model makes -- it's fetched the same way for every trip with a resolved
start date (date_resolver.py), so routing it through agent_service.py's
tool-calling loop would only add Gemini tokens for no benefit. This keeps
the feature's marginal LLM cost at zero.

Split into two small functions (client-shaped: auth-free HTTP calls, no
retries/pagination needed for this API) mirroring tools.py's
convert_currency -- never raises, always returns None/[] on failure so a
geocoding miss or an Open-Meteo outage just means "no weather shown" for
that trip, never a broken response (CLAUDE.md principle #7: no data beats
invented data).
"""
import json
from datetime import date, datetime, timedelta

import requests

from . import models

MAX_FORECAST_DAYS = 16  # Open-Meteo's daily-forecast horizon
CACHE_TTL = timedelta(hours=3)  # re-fetch Open-Meteo only once cached data is this stale

# WMO weather codes -> short human text. A plain lookup table, not an LLM
# call -- zero fabrication risk translating a code to a word.
WMO_CONDITIONS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def _celsius_to_fahrenheit(celsius: float) -> float:
    """Real Python arithmetic, not the LLM -- same "never let the model do
    the math" discipline as principle #6's date arithmetic. Open-Meteo only
    ever returns Celsius, so both units are computed once here rather than
    trusting a conversion done anywhere downstream (a prompt, a UI helper)
    that could get it wrong."""
    return round(celsius * 9 / 5 + 32, 1)


def _geocode_result(destination: str) -> dict | None:
    """Raw first result from Open-Meteo's free geocoding search, or None on
    no match/failure. Shared by geocode() (lat/lon) and geocode_timezone()
    (IANA timezone name) -- one HTTP call shape, not two independent ones
    that could drift apart."""
    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": destination, "count": 1},
            timeout=10,
        ).json()
    except Exception:
        return None

    results = resp.get("results") or []
    return results[0] if results else None


def geocode(destination: str) -> tuple[float, float] | None:
    """Resolves a free-text destination to (lat, lon) via Open-Meteo's free
    geocoding endpoint. None on no match or any failure."""
    result = _geocode_result(destination)
    if not result:
        return None
    return result["latitude"], result["longitude"]


def geocode_timezone(destination: str) -> str | None:
    """IANA timezone name for a destination (e.g. "America/New_York"), from
    the same free geocoding lookup geocode() uses -- Open-Meteo's search
    results already include a "timezone" field, so this costs no extra API
    beyond one more geocoding call. Needed because Google Calendar's REST
    API (unlike RFC 5545 .ics files -- see calendar_export.py's deliberate
    floating-time design) rejects a timed event with no timezone at all;
    confirmed live via a real "Missing time zone definition for start time"
    error pushing a trip with no timeZone set. None on no match/failure --
    callers should fall back to a neutral default (google_calendar.py falls
    back to UTC) rather than guessing a specific wrong zone."""
    result = _geocode_result(destination)
    return result.get("timezone") if result else None


def get_daily_forecast(lat: float, lon: float, start: date, num_days: int) -> list[dict]:
    """Small, flat, pre-aggregated per-day forecast list (CLAUDE.md
    principle #2) -- never the raw Open-Meteo payload. Bounded to
    MAX_FORECAST_DAYS; days beyond that (or any API failure) simply aren't
    included, rather than guessed at.

    Returns: [{"day_offset": int, "date": "YYYY-MM-DD", "temp_min": float,
    "temp_max": float, "temp_min_f": float, "temp_max_f": float,
    "condition": str}, ...] -- both units always included so a display or
    an answered question never has to convert on the fly.
    """
    num_days = max(0, min(num_days, MAX_FORECAST_DAYS))
    if num_days == 0:
        return []

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "timezone": "auto",
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=num_days - 1)).isoformat(),
            },
            timeout=15,
        ).json()
    except Exception:
        return []

    daily = resp.get("daily")
    if not daily:
        return []  # e.g. start_date beyond the forecast horizon -- Open-Meteo returns no "daily" block

    dates = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    codes = daily.get("weather_code", [])

    out = []
    for i, iso_date in enumerate(dates):
        if i >= len(highs) or i >= len(lows) or i >= len(codes):
            break  # malformed/short response -- stop rather than emit partial-nonsense rows
        out.append({
            "day_offset": i,
            "date": iso_date,
            "temp_min": lows[i],
            "temp_max": highs[i],
            "temp_min_f": _celsius_to_fahrenheit(lows[i]),
            "temp_max_f": _celsius_to_fahrenheit(highs[i]),
            "condition": WMO_CONDITIONS.get(codes[i], "Unknown"),
        })
    return out


def summarize_for_prompt(destination: str, weather: list[dict]) -> str:
    """Compact plain-text rendering of a trip's per-day forecast, meant to
    be folded into answer_question's grounding context (CLAUDE.md
    principle #7) -- the fix for a real fabrication bug: a follow-up
    question asked about weather-appropriate outfits got answered with
    plausible-sounding but wrong temperatures (~70-80F) when the real
    fetched forecast was 104-108F, because the real weather data was never
    passed to the Q&A path at all -- only the currency agent_context was.
    Returns "" for an empty list (nothing to add, caller should skip it)."""
    if not weather:
        return ""
    day_lines = [
        f"Day {w['day_number']} ({w['date']}): high {w['temp_max_f']:.0f}°F/{w['temp_max']:.0f}°C, "
        f"low {w['temp_min_f']:.0f}°F/{w['temp_min']:.0f}°C, {w['condition'].lower()}"
        for w in weather
    ]
    return f"Real weather forecast for {destination}: " + "; ".join(day_lines)


def read_cached_weather(trip: "models.Trip") -> list[dict]:
    """Returns whatever forecast is already cached on `trip.weather_json`,
    with no freshness check and no network call -- unlike
    get_or_refresh_trip_weather, this never re-fetches, even if the cache
    is stale or missing entirely (returns [] in that case, same "no data
    beats invented/stale-labeled-as-fresh data" contract as everywhere
    else in this module).

    For a conversation with several trips (one per edit turn), only the
    *latest* trip's weather actually needs a freshness check on every
    reload -- older trips are historical record at this point, and a real
    user is never looking at "is Tuesday's forecast still accurate" for a
    trip three edits ago. routers/conversations.py's get_conversation uses
    this for every trip except the latest one, instead of calling
    get_or_refresh_trip_weather for all of them -- that used to mean a
    freshness check (and, on a cache miss, a live geocode + forecast call)
    for every historical trip on every single conversation reload, scaling
    with edit count for no real benefit (found in the 2026-08-31
    architecture review).
    """
    if not trip.weather_json:
        return []
    return json.loads(trip.weather_json)


def get_or_refresh_trip_weather(trip: "models.Trip", items: list["models.ItineraryItem"]) -> list[dict]:
    """Returns a trip's per-day forecast, reading the cached
    `Trip.weather_json` when it's fresh and only hitting Open-Meteo again
    when it's missing or stale (CLAUDE.md principles #4/#5 -- cache tool
    calls, serve cached findings without re-fetching every request).
    Mutates `trip.weather_json`/`weather_fetched_at` in place on a fresh
    fetch -- the caller owns the DB session and must commit. Shared by
    both routers/trips.py (generate + get-by-id) and
    routers/conversations.py (history reload, which is what the frontend
    actually re-renders from after every turn).
    """
    if not trip.start_date or not items:
        return []

    is_stale = (
        trip.weather_fetched_at is None
        or datetime.utcnow() - trip.weather_fetched_at > CACHE_TTL
    )
    if not is_stale and trip.weather_json:
        return json.loads(trip.weather_json)

    max_day_number = max(item.day_number for item in items)
    lat_lon = geocode(trip.destination)
    if not lat_lon:
        return []  # geocoding miss/failure -- no forecast shown, nothing invented

    forecasts = get_daily_forecast(lat_lon[0], lat_lon[1], trip.start_date, max_day_number)
    weather_out = [
        {
            "day_number": f["day_offset"] + 1,
            "date": f["date"],
            "temp_min": f["temp_min"],
            "temp_max": f["temp_max"],
            "temp_min_f": f["temp_min_f"],
            "temp_max_f": f["temp_max_f"],
            "condition": f["condition"],
        }
        for f in forecasts
    ]
    trip.weather_json = json.dumps(weather_out)
    trip.weather_fetched_at = datetime.utcnow()
    return weather_out
