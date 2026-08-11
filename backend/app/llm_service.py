import json
import os

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

SYSTEM_INSTRUCTIONS = """You are a travel planning assistant. Given a user's \
request, produce a day-by-day itinerary. Respond with ONLY valid JSON, no \
markdown fences, no commentary, matching this exact shape:

{
  "destination": "string",
  "days": [
    {
      "day_number": 1,
      "items": [
        {"time_of_day": "morning", "activity": "string", "notes": "string"}
      ]
    }
  ]
}
"""


def generate_itinerary(prompt: str) -> dict:
    """Calls the local Ollama server and returns parsed itinerary JSON.

    Swapping to a cloud model later only means changing this function's
    internals -- routers/trips.py never needs to know which provider is used.
    """
    full_prompt = f"{SYSTEM_INSTRUCTIONS}\n\nUser request: {prompt}"

    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": full_prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    raw_text = response.json()["response"].strip()

    # Models sometimes wrap JSON in ```json fences despite instructions -- strip defensively.
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.replace("json\n", "", 1)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model did not return valid JSON: {exc}\nRaw: {raw_text[:500]}")
