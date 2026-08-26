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

PAUSED AGAIN (AGENT_TOOL_CALLING_ENABLED = False) as of 2026-08-26 -- but
for a different reason than weather's removal. Weather (OpenWeather, in
tools.py) was removed outright because it wasn't working reliably in
practice. Currency was re-enabled on 2026-08-25, verified live, and worked
correctly -- it's paused now purely because of a product decision that
currency conversion isn't needed, not because anything broke. See
CLAUDE.md's decision log. gather_trip_context() short-circuits to "" while
paused, same mechanism as before -- no other code path needed to change to
flip this back off. Flip AGENT_TOOL_CALLING_ENABLED back to True to bring it
back if that decision changes.

Migrated to Gemini's function-calling shape (google.genai.types) alongside
llm_service.py before this was re-enabled, so the mechanics didn't need
migrating again once it was.
"""
from google.genai import types

from . import llm_service, tools

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


def _call_gemini_with_tools(contents: list, system_instruction: str) -> types.GenerateContentResponse:
    """Thin wrapper so tests patch one call site:
    app.agent_service._call_gemini_with_tools. Returns the raw SDK response
    object (unlike llm_service._call_gemini, which unwraps to plain text/a
    parsed model) because the manual tool-loop below needs to branch on
    response.function_calls and replay response.candidates[0].content back
    into the conversation, not just read the text.

    thinking_level stays MINIMAL for the same reason as llm_service.py:
    verified live, it avoids a reasoning model burning the output-token
    budget on invisible thinking tokens. automatic_function_calling is
    explicitly disabled since this loop manages tool execution itself
    (matching today's `{"error": str(exc)}` catch pattern) rather than
    letting the SDK call Python functions on our behalf.
    """
    return llm_service._get_client().models.generate_content(
        model=llm_service.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[tools.TOOL_SCHEMAS],
            thinking_config=llm_service._THINKING_CONFIG,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )


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
    contents = [types.Content(role="user", parts=[types.Part(text=user_content)])]

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = _call_gemini_with_tools(contents, system_instruction=AGENT_SYSTEM_PROMPT)
            calls = response.function_calls or []

            if not calls:
                return (response.text or "").strip()

            # Replay the model's own function-call turn back into the
            # conversation before sending results, exactly as Gemini's
            # multi-turn tool-calling protocol expects.
            contents.append(response.candidates[0].content)

            response_parts = []
            for call in calls:
                fn_name = call.name
                fn_args = call.args or {}

                if fn_name not in tools.TOOL_FUNCTIONS:
                    result = {"error": f"Unknown tool '{fn_name}'"}
                else:
                    fn = getattr(tools, fn_name)  # dynamic lookup so patches/mocks in tests take effect
                    try:
                        result = fn(**fn_args)
                    except Exception as exc:
                        result = {"error": str(exc)}

                response_parts.append(types.Part.from_function_response(name=fn_name, response=result))

            # Function-response parts go back in a role="user" turn --
            # confirmed live against the real API: role="tool" is rejected
            # outright ("Role 'tool' is not supported"), despite that being
            # the shape Ollama's /api/chat used.
            contents.append(types.Content(role="user", parts=response_parts))

        return ""  # hit MAX_TOOL_ROUNDS without a final answer -- bail out quietly
    except Exception:
        return ""
