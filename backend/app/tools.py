"""Tool implementations the agent can call. Both APIs used here are free and
require no API key -- deliberately chosen so this works out of the box on
free-tier setups.
"""
import requests


def get_weather_forecast(city: str) -> dict:
    """Free geocoding + forecast via Open-Meteo (no API key required)."""
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=15,
    ).json()

    if not geo.get("results"):
        return {"error": f"Could not find a location matching '{city}'"}

    location = geo["results"][0]
    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 7,
        },
        timeout=15,
    ).json()

    daily = forecast.get("daily", {})
    return {
        "location": location.get("name"),
        "country": location.get("country"),
        "daily_high_c": daily.get("temperature_2m_max"),
        "daily_low_c": daily.get("temperature_2m_min"),
        "precipitation_chance_pct": daily.get("precipitation_probability_max"),
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
                "Get a 7-day weather forecast for a city. Useful for packing "
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
