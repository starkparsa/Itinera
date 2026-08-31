"""Three genuine agentic tool-calling loops: the model itself decides
whether it needs to call a tool based on what it's given, we execute
whatever it asks for, and feed results back until it's done.

This is deliberately kept separate from llm_service.py's itinerary
generation, which stays a reliable, deterministic chunked pipeline.

gather_trip_context() (currency conversion) runs once, up front, to gather
optional context (e.g. "your budget converts to X local currency") that
then gets folded into the itinerary prompts as plain text.

gather_place_context_for_itinerary() (place-context via Wikipedia,
2026-08-29) also runs once, up front, alongside gather_trip_context --
looking up real background (history, character of the area) for the
trip's destination and any specific places named in the request, folded
into the same itinerary-prompt text. Added so itinerary generation itself
gets real grounded place context, not just conversational Q&A -- see
CLAUDE.md's decision log ("Place context" row) for why this was originally
scoped as Q&A-only and what changed.

answer_question_with_tools() (place-context via Wikipedia) runs fresh on
every conversational question turn instead. This loop and
gather_place_context_for_itinerary() call the exact same underlying tool
(get_place_context) but are kept as separate loops/flags/schema wrappers
for the same caching reason gather_trip_context is separate from both:
routers/trips.py caches whatever generate_itinerary() returns as
"agent_context" once per conversation forever (`Conversation.agent_context
is None` gate), which is correct for a trip's background facts (true for
the whole trip) but would be wrong for conversational place-context
questions (a different place can be asked about on every turn -- caching
the first answer forever would silently reuse it for every later
question). Each loop is also given only its own tool's schema
(tools.CURRENCY_TOOL_SCHEMAS / tools.QA_TOOL_SCHEMAS /
tools.PLANNING_TOOL_SCHEMAS, not the combined tools.TOOL_SCHEMAS) so
flipping one loop's kill switch never makes another loop's tool reachable
as a side effect.

AGENT_TOOL_CALLING_ENABLED (currency) is PAUSED (False) as of 2026-08-26 --
but for a different reason than weather's removal. Weather (OpenWeather, in
tools.py) was removed outright because it wasn't working reliably in
practice. Currency was re-enabled on 2026-08-25, verified live, and worked
correctly -- it's paused now purely because of a product decision that
currency conversion isn't needed, not because anything broke. See
CLAUDE.md's decision log. gather_trip_context() short-circuits to "" while
paused, same mechanism as before. Flip AGENT_TOOL_CALLING_ENABLED back to
True to bring it back if that decision changes.

QA_TOOL_CALLING_ENABLED (conversational place-context) and
PLANNING_TOOL_CALLING_ENABLED (itinerary-planning place-context) both
default to True -- neither is something that was ever paused.

Migrated to Gemini's function-calling shape (google.genai.types) alongside
llm_service.py before currency was re-enabled, so the mechanics didn't need
migrating again once it was.
"""
from google.genai import types

from . import llm_service, tools

MAX_TOOL_ROUNDS = 4

AGENT_TOOL_CALLING_ENABLED = False

QA_TOOL_CALLING_ENABLED = True

PLANNING_TOOL_CALLING_ENABLED = True

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

QA_TOOL_SYSTEM_PROMPT = """You are a travel planning assistant answering a \
follow-up question in an ongoing conversation. You have a tool, \
get_place_context, that looks up real information about a named place \
(landmark, neighborhood, city) from Wikipedia. Call it when the question \
names or clearly implies a specific place and you'd otherwise be guessing \
about it -- don't call it for things already covered by the conversation \
history or the real data given to you below.

Default to detail="brief" -- only pass detail="detailed" when the user's \
own words ask for more (e.g. "tell me the full history", "give me more \
detail"). A brief overview is the right amount of information for normal \
trip-planning questions; a full history is not. Being asked to "be my \
tour guide" changes your voice/persona, not the detail level by itself.

If this message asks you to be a tour guide (or similar) WITHOUT naming a \
specific place, do not recap the whole itinerary day-by-day or narrate \
every stop already listed in the conversation -- give a short, friendly \
welcome instead (a sentence or two) and let the user ask about whichever \
stop they want to hear about first. Only go into an actual place's \
detail once they name one.

Match your reply's length to the detail level you used, not your own \
general knowledge of the place: after a detail="brief" call, answer in \
2-4 sentences using mainly what the tool gave you -- do not pad it out \
with extra facts, dates, or trivia you happen to know. Save the fuller, \
multi-paragraph answer for when you actually used detail="detailed".

If a tool result contains an "error" field, that specific information is \
unavailable -- say so briefly rather than inventing a plausible-sounding \
fact to fill the gap.

This applies just as much when the tool call succeeds: only name a \
specific business, restaurant, museum, gallery, or street address if it \
came from the tool's result or was already mentioned earlier in this \
conversation. Never invent a specific venue name or address to make a \
"tour guide"-style answer sound more detailed -- describe the kind of \
experience instead (e.g. "grab a plate of Haitian food at a local spot" \
rather than naming a restaurant you don't actually have data on). A \
guided-sounding answer built from real, general facts is correct; one \
padded with invented specifics is not.

Answer directly and conversationally once you have what you need."""

PLANNING_TOOL_SYSTEM_PROMPT = """You are helping plan a trip, before any \
itinerary is written. You have a tool, get_place_context, that looks up \
real background information about a named place (city, neighborhood, \
landmark) from Wikipedia. Call it for the trip's destination, and for any \
specific neighborhood, landmark, or district explicitly named in the \
request, so the itinerary you're about to help write is grounded in real \
facts -- history, character of the area, what it's actually known for. \
Call it at most 2-3 times; look up the destination and, at most, one or \
two other places the request specifically names -- do not look up every \
possible point of interest, this is background grounding, not research.

Default to detail="brief" for this -- itinerary generation needs a short, \
useful fact base, not a full history. Reply with a short plain-text \
summary, 2-5 sentences, of anything useful you found that should inform \
the itinerary. Do not write the itinerary itself here, and do not adopt a \
narrative or "tour guide" tone -- this summary is internal grounding for \
another step, not a reply shown to the user.

If a tool result contains an "error" field, that specific place's data is \
unavailable -- do not invent a plausible-sounding fact to fill the gap. \
Leave it out of your summary (or say briefly that it wasn't available) \
rather than guessing."""


def _call_gemini_with_tools(
    contents: list, system_instruction: str, tool_schema: types.Tool
) -> types.GenerateContentResponse:
    """Thin wrapper so tests patch one call site:
    app.agent_service._call_gemini_with_tools. Returns the raw SDK response
    object (unlike llm_service._call_gemini, which unwraps to plain text/a
    parsed model) because the manual tool-loop below needs to branch on
    response.function_calls and replay response.candidates[0].content back
    into the conversation, not just read the text.

    tool_schema: the caller's own tool_schema only (tools.CURRENCY_TOOL_SCHEMAS
    or tools.QA_TOOL_SCHEMAS) -- never tools.TOOL_SCHEMAS, which combines
    every tool this module knows about and would let one loop reach the
    other loop's tool.

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
            tools=[tool_schema],
            thinking_config=llm_service._THINKING_CONFIG,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )


def _run_tool_loop(contents: list, system_instruction: str, tool_schema: types.Tool) -> str:
    """The manual tool-calling round trip shared by gather_trip_context and
    answer_question_with_tools -- the mechanics (thinking_level, role="user"
    for function responses, MAX_TOOL_ROUNDS, quiet failure) are identical
    between the two; only which tool is exposed, what system prompt is
    used, and how the caller treats the result (cached once vs. run fresh
    every turn) differ. See this module's docstring for why those two
    loops stay separate rather than sharing one flag/schema.
    """
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = _call_gemini_with_tools(contents, system_instruction, tool_schema)
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


def gather_trip_context(prompt: str, destination: str | None = None) -> str:
    """Runs the currency tool-calling loop and returns a short plain-text
    summary to fold into itinerary generation, or "" if nothing useful was
    found, the loop fails for any reason, or the agent step is currently
    paused (see AGENT_TOOL_CALLING_ENABLED above).

    Tool use here is a nice-to-have, not a hard dependency -- if the model
    doesn't support tool calling well, or a tool API is unreachable, this
    fails quietly and itinerary generation proceeds exactly as it did before
    this feature existed.

    destination: optional, folded into the user message so the model isn't
    left guessing which city to check. Needed when this is called from a
    bare follow-up question (e.g. "what does the temperature look like?")
    that doesn't name a place on its own -- the original trip-generation
    prompt usually does, so callers with that context can omit this.

    Caching note for callers: this function does no caching itself.
    routers/trips.py caches its result once per Conversation forever, which
    is correct here because currency is one fact true for the whole trip --
    do NOT apply that same caching pattern to answer_question_with_tools
    below, see its docstring.
    """
    if not AGENT_TOOL_CALLING_ENABLED:
        return ""

    user_content = f"Trip destination: {destination}\n\n{prompt}" if destination else prompt
    contents = [types.Content(role="user", parts=[types.Part(text=user_content)])]
    return _run_tool_loop(contents, AGENT_SYSTEM_PROMPT, tools.CURRENCY_TOOL_SCHEMAS)


def gather_place_context_for_itinerary(prompt: str) -> str:
    """Runs a place-context (Wikipedia) tool-calling loop over the raw trip
    request and returns a short plain-text summary to fold into itinerary
    generation, or "" if nothing useful was found, the loop fails for any
    reason, or this step is currently disabled (see
    PLANNING_TOOL_CALLING_ENABLED above).

    Deliberately takes only `prompt`, the same shape as gather_trip_context
    -- no destination parameter, even though llm_service.generate_itinerary
    calls this concurrently with the destination-inference step and so
    doesn't have a resolved destination to pass in yet. The model reads the
    destination straight out of the raw prompt text itself, exactly like
    gather_trip_context already does for its own first call -- there's no
    need to block this on _infer_trip_meta finishing first.

    Tool use here is a nice-to-have, not a hard dependency -- if the model
    doesn't support tool calling well, or Wikipedia is unreachable, this
    fails quietly and itinerary generation proceeds exactly as it did
    before this feature existed.

    Caching note for callers: this function does no caching itself. Like
    gather_trip_context, its result is meant to be combined into the same
    "agent_context" string llm_service.generate_itinerary returns, which
    routers/trips.py caches once per Conversation forever -- correct here
    because a trip's real-world background facts don't change turn to
    turn, unlike answer_question_with_tools's per-question place lookups
    (see this module's docstring for why that loop stays separate and
    uncached).
    """
    if not PLANNING_TOOL_CALLING_ENABLED:
        return ""

    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    return _run_tool_loop(contents, PLANNING_TOOL_SYSTEM_PROMPT, tools.PLANNING_TOOL_SCHEMAS)


def answer_question_with_tools(
    prompt: str, chat_messages: list[dict], agent_context: str = "", tour_guide_mode: bool = False,
) -> str:
    """Runs the place-context tool-calling loop for a conversational
    follow-up question and returns a plain-text answer, or "" if the step
    is disabled, fails for any reason, or MAX_TOOL_ROUNDS is exceeded.

    Callers MUST run this fresh on every question-intent turn -- do NOT
    wrap it in a once-per-conversation cache the way routers/trips.py
    caches gather_trip_context's result. That pattern is correct for
    currency (one fact, true for the whole trip) but wrong here: a
    different place can be asked about on every turn, and caching the
    first answer forever would silently reuse it for every later question
    in the same conversation. "" should be treated by the caller as "fall
    back to llm_service.answer_question", the same "fails quietly, never
    blocks the turn" contract gather_trip_context already has.

    chat_messages: real chat-formatted history (list of {"role","content"}
    dicts, this app's stored-message shape), same input llm_service.
    answer_question already takes -- needed so the model has conversational
    continuity (e.g. "what about its history?" referring back to a place
    named a few turns earlier).

    agent_context: the same combined currency+weather grounding string
    routers/trips.py already builds for llm_service.answer_question, passed
    through here too so this loop doesn't lose access to real data (and
    doesn't re-ask a tool for something already known) just because it
    takes a different code path.

    tour_guide_mode: True when this conversation is already in persistent
    tour-guide mode from an earlier turn (Conversation.tour_guide_mode,
    set by routers/trips.py when a PAST turn's classify_intent returned
    tour_guide_requested=True). Distinct from QA_TOOL_SYSTEM_PROMPT's
    existing per-turn "be my tour guide" instruction, which only covers
    THIS turn's own wording -- this flag keeps the tour-guide *persona*
    going on later turns that don't repeat that phrasing. The triggering
    turn itself doesn't need this True yet (QA_TOOL_SYSTEM_PROMPT already
    handles it), so callers should pass the conversation's state as it
    stood *entering* this turn, not including any update this turn makes.

    As of 2026-08-29 this does NOT force detail="detailed" on later turns
    (a deliberate reversal of this flag's original 2026-08-27 behavior,
    made once the fabrication risk that motivated forcing "detailed" was
    fixed a different way -- see QA_TOOL_SYSTEM_PROMPT's own anti-invention
    instruction) -- every turn, guide mode or not, now defaults to brief;
    this flag only changes persona/voice and reinforces that default, it
    doesn't override the per-turn escalate-only-if-asked logic below.
    """
    if not QA_TOOL_CALLING_ENABLED:
        return ""

    system_instruction = QA_TOOL_SYSTEM_PROMPT
    if tour_guide_mode:
        system_instruction += (
            "\n\nYou are continuing an ongoing tour-guide-style conversation "
            "-- the user explicitly asked you to be their tour guide earlier "
            "in this chat, and that request still stands even though this "
            "specific message may not repeat it. Keep speaking in that "
            "tour-guide voice. For each new question, default to a short, "
            "focused summary of exactly what's being asked plus a brief bit "
            "of relevant history -- call get_place_context with "
            "detail=\"brief\" unless THIS message's own wording explicitly "
            "asks to go deeper (e.g. \"tell me more\", \"go deeper\", \"the "
            "full history\"), in which case use detail=\"detailed\" and give "
            "the fuller answer for that turn only. Do not carry an earlier "
            "message's request for more detail forward -- judge each new "
            "question on its own wording, the same way you would if this "
            "were the first question in the conversation."
        )
    if agent_context:
        system_instruction += (
            f"\n\nReal data gathered earlier for this trip (for your reference "
            f"only): {agent_context}\n"
        )

    contents = [
        types.Content(role=("model" if m["role"] == "assistant" else "user"), parts=[types.Part(text=m["content"])])
        for m in chat_messages
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))

    return _run_tool_loop(contents, system_instruction, tools.QA_TOOL_SCHEMAS)
