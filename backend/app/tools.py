"""Tool implementations.

Weather is fetched deterministically from the resolved destination (geocode
then lat/lon forecast via Open-Meteo) -- not left to the agent to guess a
city name. Currency conversion is still an optional agent tool.
"""
import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 16  # Open-Meteo's free daily-forecast horizon


def _condition_label(code: int) -> str:
    """Maps WMO weather interpretation codes to a short English label."""
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or 85 <= code <= 86:
        return "snow"
    if 95 <= code <= 99:
        return "thunderstorm"
    return "mixed conditions"


def _geocode(place: str) -> dict | None:
    """Resolves a destination string to the best Open-Meteo geocoding hit.

    Tries the full string first, then the part before a comma (so
    "Kyoto, Japan" still works if the API wants just the city). Prefers a
    result whose country matches text in the query, then highest population
    so "Paris" is France rather than Texas.
    """
    queries = [place.strip()]
    if "," in place:
        queries.append(place.split(",", 1)[0].strip())

    place_lower = place.lower()
    seen: set[str] = set()
    for query in queries:
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())

        resp = requests.get(
            GEOCODING_URL,
            params={"name": query, "count": 5, "language": "en", "format": "json"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            continue

        country_matches = [
            r for r in results
            if (r.get("country") or "").lower() in place_lower
            or (r.get("country_code") or "").lower() in place_lower
        ]
        pool = country_matches or results
        return max(pool, key=lambda r: r.get("population") or 0)
    return None


def get_weather_forecast(place: str, days: int = 7) -> dict:
    """Daily forecast for a destination via Open-Meteo.

    Geocodes first, then requests native daily high/low, precipitation
    probability, and weather code at that lat/lon. Horizon is capped at
    MAX_FORECAST_DAYS; longer trips get a note rather than invented weather.
    Failures return {"error": ...} so callers can proceed without weather.
    """
    if not place or place.strip().lower() == "unknown":
        return {"error": "No destination to geocode"}

    try:
        geo = _geocode(place)
        if not geo:
            return {"error": f"Could not geocode '{place}'"}

        requested_days = max(1, int(days))
        forecast_days = min(requested_days, MAX_FORECAST_DAYS)
        resp = requests.get(
            FORECAST_URL,
            params={
                "latitude": geo["latitude"],
                "longitude": geo["longitude"],
                "daily": (
                    "weather_code,temperature_2m_max,"
                    "temperature_2m_min,precipitation_probability_max"
                ),
                "timezone": "auto",
                "forecast_days": forecast_days,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily") or {}
        times = daily.get("time") or []
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        pops = daily.get("precipitation_probability_max") or []
        codes = daily.get("weather_code") or daily.get("weathercode") or []

        days_out = []
        for i, date in enumerate(times):
            code = codes[i] if i < len(codes) and codes[i] is not None else None
            high = highs[i] if i < len(highs) else None
            low = lows[i] if i < len(lows) else None
            pop = pops[i] if i < len(pops) else None
            days_out.append({
                "date": date,
                "high_c": round(high, 1) if high is not None else None,
                "low_c": round(low, 1) if low is not None else None,
                "precip_chance_pct": round(pop) if pop is not None else None,
                "condition": _condition_label(int(code)) if code is not None else "unknown",
            })

        result = {
            "location": geo.get("name", place),
            "country": geo.get("country"),
            "admin1": geo.get("admin1"),
            "latitude": geo.get("latitude"),
            "longitude": geo.get("longitude"),
            "timezone": data.get("timezone"),
            "days": days_out,
        }
        if requested_days > MAX_FORECAST_DAYS:
            result["note"] = (
                f"Forecast only covers the first {MAX_FORECAST_DAYS} days; "
                "later days have no reliable forecast."
            )
        return result
    except Exception as exc:
        return {"error": str(exc)}


def format_weather_context(
    forecast: dict,
    start_day: int = 1,
    end_day: int | None = None,
) -> str:
    """Turns a forecast into dated per-itinerary-day text for LLM prompts.

    Itinerary day 1 maps to the first forecast date (today in the
    destination timezone). Days past the forecast horizon are called out
    explicitly so the model does not invent weather for them.
    """
    if not forecast or forecast.get("error") or not forecast.get("days"):
        return ""

    days = forecast["days"]
    last_day = end_day if end_day is not None else max(start_day, len(days))
    location = forecast.get("location") or ""
    country = forecast.get("country")
    loc = f"{location}, {country}" if country else location

    lines = [
        f"Weather forecast for {loc} (use this for packing and indoor vs "
        f"outdoor choices; do not invent weather beyond these days):"
    ]
    for day_number in range(start_day, last_day + 1):
        idx = day_number - 1
        if idx >= len(days):
            lines.append(
                f"Day {day_number}: no forecast available — do not invent specific weather."
            )
            continue
        if idx < 0:
            continue
        day = days[idx]
        parts = []
        if day.get("low_c") is not None and day.get("high_c") is not None:
            parts.append(f"{day['low_c']}–{day['high_c']}°C")
        if day.get("precip_chance_pct") is not None:
            parts.append(f"{day['precip_chance_pct']}% chance of precipitation")
        if day.get("condition"):
            parts.append(day["condition"])
        date = day.get("date") or ""
        date_bit = f" ({date})" if date else ""
        lines.append(f"Day {day_number}{date_bit}: {', '.join(parts)}")

    if forecast.get("note"):
        lines.append(forecast["note"])
    return "\n".join(lines)


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


# JSON schemas describing each tool to the model, in the format Ollama's
# /api/chat tools field expects. Weather is intentionally not here -- it is
# fetched from the resolved destination in llm_service, not guessed by the agent.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "convert_currency",
            "description": "Convert an amount of money from one currency to another using current exchange rates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Amount to convert"},
                    "from_currency": {"type": "string", "description": "3-letter currency code, e.g. USD"},
                    "to_currency": {"type": "string", "description": "3-letter currency code, e.g. EUR"},
                },
                "required": ["amount", "from_currency", "to_currency"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "convert_currency": convert_currency,
}
