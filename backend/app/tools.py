"""Tool implementations the agent can call.

Currency conversion uses the free, no-key Frankfurter API. A weather tool
(OpenWeather) used to live here too -- removed after it proved unreliable
in practice; see CLAUDE.md's decision log. convert_currency isn't actively
reachable right now either -- it's still gated behind agent_service.py's
AGENT_TOOL_CALLING_ENABLED, paused as a product decision (see that
module's docstring). get_place_context is a separate tool reached through
a different, always-on loop (agent_service.answer_question_with_tools) --
see that function's docstring for why the two use separate loops/flags.

TOOL_SCHEMAS is in Gemini's function-calling shape (google.genai.types) as
of the Gemini migration -- previously Ollama's dict-list shape.
"""
import requests
from google.genai import types

from .clients import wikipedia_client

_BRIEF_CHAR_CAP = 320  # enforced even if Wikipedia's own extract runs long,
                        # so "brief" stays genuinely brief regardless of topic
_DETAILED_CHAR_CAP = 2000  # bounded even in "detailed" mode -- never unbounded


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


# Gemini-shaped tool schema (google.genai.types.Tool / FunctionDeclaration),
# passed to GenerateContentConfig(tools=[...]) in agent_service.py.
#
# Split into per-loop schemas, not just one merged list: agent_service.py
# runs two SEPARATE tool-calling loops (gather_trip_context for currency,
# answer_question_with_tools for place-context) with different caching
# semantics and different kill switches (AGENT_TOOL_CALLING_ENABLED vs.
# QA_TOOL_CALLING_ENABLED). If both tools were advertised to both loops via
# one shared schema, flipping QA_TOOL_CALLING_ENABLED on would silently
# make convert_currency reachable again too, defeating its own pause. Each
# loop must only ever see the schema for the tool(s) it owns.
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

# Used by agent_service.gather_trip_context (currency only).
CURRENCY_TOOL_SCHEMAS = types.Tool(function_declarations=[_CONVERT_CURRENCY_DECLARATION])

# Used by agent_service.answer_question_with_tools (place-context only).
QA_TOOL_SCHEMAS = types.Tool(function_declarations=[_GET_PLACE_CONTEXT_DECLARATION])

# Everything this module can do, for tests/introspection -- never pass this
# combined list into a live GenerateContentConfig(tools=[...]) call, or a
# loop's kill switch stops actually isolating its tool.
TOOL_SCHEMAS = types.Tool(function_declarations=[
    _CONVERT_CURRENCY_DECLARATION,
    _GET_PLACE_CONTEXT_DECLARATION,
])

TOOL_FUNCTIONS = {
    "convert_currency": convert_currency,
    "get_place_context": get_place_context,
}
