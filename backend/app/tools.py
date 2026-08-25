"""Tool implementations the agent can call.

Currency conversion uses the free, no-key Frankfurter API. A weather tool
(OpenWeather) used to live here too -- removed after it proved unreliable
in practice; see CLAUDE.md's decision log. The whole agent tool-calling
step is currently paused (see agent_service.py), so this module's only
remaining tool isn't actively invoked right now either, but is kept ready
for when that's re-enabled.

TOOL_SCHEMAS is in Gemini's function-calling shape (google.genai.types) as
of the Gemini migration -- previously Ollama's dict-list shape.
"""
import requests
from google.genai import types


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


# Gemini-shaped tool schema (google.genai.types.Tool / FunctionDeclaration),
# passed to GenerateContentConfig(tools=[...]) in agent_service.py.
TOOL_SCHEMAS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
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
    ),
])

TOOL_FUNCTIONS = {
    "convert_currency": convert_currency,
}
