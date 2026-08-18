import json
import os

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

# Chunking is the fix for long trips: rather than asking the model to write
# one giant JSON blob for a 30-day trip (unreliable -- local models degrade
# at long structured output and risk truncation no matter how large the
# context window is set), we generate a few days at a time and stitch the
# results together. Each individual call stays small and fast regardless of
# how long the overall trip is.
CHUNK_SIZE_DAYS = 5
MAX_TOTAL_DAYS = 60  # sane upper bound so a wild request doesn't run forever
DEFAULT_TOTAL_DAYS = 7

META_INSTRUCTIONS = """Given a trip request, identify the destination and \
the total number of days the trip should span. If a duration isn't stated, \
estimate a reasonable one (a "week" = 7, a "month" = 30, a "long weekend" = \
3). Respond with ONLY valid JSON, no markdown fences, no commentary:

{"destination": "string", "total_days": integer}
"""

CHUNK_INSTRUCTIONS_TEMPLATE = """You are a travel planning assistant \
writing part of a longer itinerary. The trip is: {prompt}
Destination: {destination}
This trip runs for {total_days} days total. Write ONLY days {start_day} \
through {end_day} of it -- do not write any other days.
{covered_note}
Respond with ONLY valid JSON, no markdown fences, no commentary, matching \
this exact shape:

{{
  "days": [
    {{
      "day_number": {start_day},
      "items": [
        {{"time_of_day": "morning", "activity": "string", "notes": "string"}}
      ]
    }}
  ]
}}
"""


def _call_ollama(prompt: str, num_predict: int, num_ctx: int = 8192) -> str:
    """Sends a prompt to Ollama and returns the raw text response."""
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict},
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


def _parse_json(raw_text: str) -> dict:
    """Parses a model response as JSON, stripping markdown fences and giving
    a clear error (including a truncation hint) if parsing fails."""
    text = raw_text
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        looks_truncated = not text.rstrip().endswith("}")
        hint = " (response appears cut off)" if looks_truncated else ""
        raise ValueError(f"Model did not return valid JSON{hint}: {exc}\nRaw: {text[:800]}")


def _infer_trip_meta(prompt: str, requested_days: int | None) -> tuple[str, int]:
    """Figures out destination and total trip length.

    If the caller already knows the day count (e.g. from a UI field), we
    still ask the model for the destination alone via the same call, but
    total_days from the request always wins over the model's guess.
    """
    raw = _call_ollama(f"{META_INSTRUCTIONS}\n\nTrip request: {prompt}", num_predict=200)
    try:
        meta = _parse_json(raw)
        destination = meta.get("destination", "Unknown")
        inferred_days = int(meta.get("total_days", DEFAULT_TOTAL_DAYS))
    except (ValueError, TypeError):
        destination = "Unknown"
        inferred_days = DEFAULT_TOTAL_DAYS

    total_days = requested_days if requested_days else inferred_days
    total_days = max(1, min(total_days, MAX_TOTAL_DAYS))
    return destination, total_days


def _generate_chunk(prompt: str, destination: str, total_days: int, start_day: int, end_day: int, covered_activities: list[str]) -> list[dict]:
    covered_note = ""
    if covered_activities:
        recent = ", ".join(covered_activities[-15:])
        covered_note = f"Already covered on earlier days (avoid repeating these): {recent}\n"

    chunk_prompt = CHUNK_INSTRUCTIONS_TEMPLATE.format(
        prompt=prompt,
        destination=destination,
        total_days=total_days,
        start_day=start_day,
        end_day=end_day,
        covered_note=covered_note,
    )
    # Budget output tokens roughly per day so bigger chunks still get enough room.
    num_predict = 350 * (end_day - start_day + 1)
    raw = _call_ollama(chunk_prompt, num_predict=num_predict)
    parsed = _parse_json(raw)
    return parsed.get("days", [])


def generate_itinerary(prompt: str, requested_days: int | None = None) -> dict:
    """Calls the local Ollama server and returns a complete itinerary,
    generating it in day-range chunks so trip length doesn't degrade output
    quality or risk truncation.

    Swapping to a cloud model later only means changing this function's
    internals -- routers/trips.py never needs to know which provider is used.
    """
    destination, total_days = _infer_trip_meta(prompt, requested_days)

    all_days: list[dict] = []
    covered_activities: list[str] = []

    for start_day in range(1, total_days + 1, CHUNK_SIZE_DAYS):
        end_day = min(start_day + CHUNK_SIZE_DAYS - 1, total_days)
        chunk_days = _generate_chunk(prompt, destination, total_days, start_day, end_day, covered_activities)
        all_days.extend(chunk_days)
        for day in chunk_days:
            for item in day.get("items", []):
                if item.get("activity"):
                    covered_activities.append(item["activity"])

    result = {"destination": destination, "days": all_days}
    if requested_days and requested_days > MAX_TOTAL_DAYS:
        result["note"] = f"Requested {requested_days} days exceeds the {MAX_TOTAL_DAYS}-day limit; showing the first {MAX_TOTAL_DAYS} days."
    return result
