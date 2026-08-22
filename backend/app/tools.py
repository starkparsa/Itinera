"""Tool implementations the agent can call.

Weather uses the OpenWeather API (requires OPENWEATHER_API_KEY). Currency
conversion still uses the free, no-key Frankfurter API.
"""
import os
from collections import defaultdict

import requests

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")


def get_weather_forecast(city: str) -> dict:
    """5-day/3-hour forecast via OpenWeather, aggregated into daily
    highs/lows/precipitation chance. Uses the free-tier /forecast endpoint --
    OpenWeather's daily-resolution forecast requires a separate paid-adjacent
    One Call subscription, so this endpoint works with any standard API key.
    """
    if not OPENWEATHER_API_KEY:
        return {"error": "OPENWEATHER_API_KEY is not configured"}

    resp = requests.get(
        "https://api.openweathermap.org/data/2.5/forecast",
        params={"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"},
        timeout=15,
    ).json()

    if str(resp.get("cod")) != "200":
        return {"error": resp.get("message", f"Could not fetch forecast for '{city}'")}

    # The API returns 3-hour interval entries; group them by calendar date
    # and reduce to a daily high/low/precipitation-chance summary.
    by_date = defaultdict(lambda: {"temps": [], "pop": []})
    for entry in resp.get("list", []):
        date = entry["dt_txt"].split(" ")[0]
        by_date[date]["temps"].append(entry["main"]["temp"])
        by_date[date]["pop"].append(entry.get("pop", 0) * 100)  # OpenWeather gives 0-1, convert to %

    dates = sorted(by_date.keys())
    return {
        "location": resp.get("city", {}).get("name", city),
        "country": resp.get("city", {}).get("country"),
        "daily_high_c": [round(max(by_date[d]["temps"]), 1) for d in dates],
        "daily_low_c": [round(min(by_date[d]["temps"]), 1) for d in dates],
        "precipitation_chance_pct": [round(max(by_date[d]["pop"]), 1) for d in dates],
    }


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
# /api/chat tools field expects.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": (
                "Get a 5-day weather forecast for a city. Useful for packing "
                "advice or planning outdoor activities around."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name, e.g. 'Kyoto' or 'Paris'"},
                },
                "required": ["city"],
            },
        },
    },
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
    "get_weather_forecast": get_weather_forecast,
    "convert_currency": convert_currency,
}
