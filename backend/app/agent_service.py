"""A genuine agentic tool-calling loop: the model itself decides whether it
needs to call the weather or currency tools based on the trip request, we
execute whatever it asks for, and feed results back until it's done.

This is deliberately kept separate from llm_service.py's itinerary
generation, which stays a reliable, deterministic chunked pipeline. This
agent step runs once, up front, to gather optional context (e.g. "it'll be
rainy" or "your budget converts to X local currency") that then gets folded
into the itinerary prompts as plain text -- the itinerary writer never has
to make tool-calling decisions itself, only the agent step does.
"""
import json
import os

import requests

from . import tools

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

MAX_TOOL_ROUNDS = 4

AGENT_SYSTEM_PROMPT = """You are a travel planning assistant with access to \
tools for checking weather and currency conversion. Given a trip request, \
call a tool only if it would meaningfully help -- e.g. checking weather for \
packing advice, or converting a stated budget to the local currency. Don't \
call tools for things you already know or that don't need real-time data. \
Once you have what you need (or if no tools are needed), reply with a \
short plain-text summary, 2-4 sentences, of anything useful you found that \
should inform the itinerary. Do not write the itinerary itself here."""


def gather_trip_context(prompt: str) -> str:
    """Runs the tool-calling loop and returns a short plain-text summary to
    fold into itinerary generation, or "" if nothing useful was found or the
    loop fails for any reason.

    Tool use here is a nice-to-have, not a hard dependency -- if the model
    doesn't support tool calling well, or a tool API is unreachable, this
    fails quietly and itinerary generation proceeds exactly as it did before
    this feature existed.
    """
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
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
