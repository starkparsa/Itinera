"""A genuine agentic tool-calling loop: the model itself decides whether it
needs to call a tool (currently just currency conversion) based on the trip
request, we execute whatever it asks for, and feed results back until it's
done.

This is deliberately kept separate from llm_service.py's itinerary
generation, which stays a reliable, deterministic chunked pipeline. This
agent step runs once, up front, to gather optional context (e.g. "your
budget converts to X local currency") that then gets folded into the
itinerary prompts as plain text -- the itinerary writer never has to make
tool-calling decisions itself, only the agent step does.

PAUSED for now (AGENT_TOOL_CALLING_ENABLED = False): the weather tool this
loop used to also call (OpenWeather, in tools.py) wasn't working reliably in
practice, so it was removed outright; currency conversion was paused
alongside it too rather than leaving a half-working agent step running.
gather_trip_context() short-circuits to "" below without any I/O while
paused -- callers don't need to change, they just get "no findings" the
same way they already handle an agent step that found nothing useful.
Flip the flag back to True (and re-add a weather tool to tools.py, if
wanted) to re-enable.
"""
import json
import os

import requests

from . import tools

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
KEEP_ALIVE = "30m"  # keeps the model resident between calls -- avoids reload latency

MAX_TOOL_ROUNDS = 4

AGENT_TOOL_CALLING_ENABLED = False

AGENT_SYSTEM_PROMPT = """You are a travel planning assistant with access to \
a tool for currency conversion. Given a trip request, call the tool only if \
it would meaningfully help -- e.g. converting a stated budget to the local \
currency. Don't call it for things you already know or that don't need \
real-time data. Once you have what you need (or if no tool call is \
needed), reply with a short plain-text summary, 2-4 sentences, of anything \
useful you found that should inform the itinerary. Do not write the \
itinerary itself here.

If a tool result contains an "error" field, that specific data is \
unavailable -- do not invent a plausible-sounding number or fact to fill \
the gap. Leave that fact out of your summary (or say briefly that it \
wasn't available) rather than guessing."""


def gather_trip_context(prompt: str, destination: str | None = None) -> str:
    """Runs the tool-calling loop and returns a short plain-text summary to
    fold into itinerary generation, or "" if nothing useful was found, the
    loop fails for any reason, or the agent step is currently paused (see
    AGENT_TOOL_CALLING_ENABLED above).

    Tool use here is a nice-to-have, not a hard dependency -- if the model
    doesn't support tool calling well, or a tool API is unreachable, this
    fails quietly and itinerary generation proceeds exactly as it did before
    this feature existed.

    destination: optional, folded into the user message so the model isn't
    left guessing which city to check. Needed when this is called from a
    bare follow-up question (e.g. "what does the temperature look like?")
    that doesn't name a place on its own -- the original trip-generation
    prompt usually does, so callers with that context can omit this.
    """
    if not AGENT_TOOL_CALLING_ENABLED:
        return ""

    user_content = f"Trip destination: {destination}\n\n{prompt}" if destination else prompt
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "tools": tools.TOOL_SCHEMAS,
                    "stream": False,
                    "keep_alive": KEEP_ALIVE,
                    "options": {"num_ctx": 4096},
                },
                timeout=120,
            )
            response.raise_for_status()
            message = response.json().get("message", {})
            tool_calls = message.get("tool_calls") or []

            if not tool_calls:
                return (message.get("content") or "").strip()

            messages.append(message)
            for call in tool_calls:
                fn_name = call.get("function", {}).get("name")
                fn_args = call.get("function", {}).get("arguments", {}) or {}

                if fn_name not in tools.TOOL_FUNCTIONS:
                    result = {"error": f"Unknown tool '{fn_name}'"}
                else:
                    fn = getattr(tools, fn_name)  # dynamic lookup so patches/mocks in tests take effect
                    try:
                        result = fn(**fn_args)
                    except Exception as exc:
                        result = {"error": str(exc)}

                messages.append({"role": "tool", "content": json.dumps(result)})

        return ""  # hit MAX_TOOL_ROUNDS without a final answer -- bail out quietly
    except Exception:
        return ""
