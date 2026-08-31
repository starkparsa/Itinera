from unittest.mock import Mock, patch

from app import agent_service


def _mock_function_call(name: str, args: dict) -> Mock:
    call = Mock()
    call.name = name
    call.args = args
    return call


def _mock_tool_response(text: str | None = None, function_calls: list | None = None) -> Mock:
    """Fakes google.genai's GenerateContentResponse shape well enough for
    gather_trip_context's loop: .function_calls (None or a list of
    FunctionCall-like objects with .name/.args), .text, and
    .candidates[0].content (the "model" turn replayed back into the
    conversation when there IS a tool call)."""
    resp = Mock()
    resp.function_calls = function_calls
    resp.text = text
    resp.candidates = [Mock(content=Mock(role="model"))]
    return resp


def test_agent_step_short_circuits_to_empty_when_disabled():
    # When AGENT_TOOL_CALLING_ENABLED is False (the kill switch for this
    # step -- e.g. if currency proves unreliable too, same as weather did),
    # gather_trip_context must short-circuit to "" without touching the
    # network at all.
    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", False),
        patch("app.agent_service._call_gemini_with_tools") as mock_call,
    ):
        result = agent_service.gather_trip_context("weekend in Chicago")

    assert result == ""
    mock_call.assert_not_called()


def test_no_tool_needed_returns_content_directly():
    response = _mock_tool_response(text="No special context needed for this trip.")

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response),
    ):
        result = agent_service.gather_trip_context("weekend in Chicago")

    assert result == "No special context needed for this trip."


def test_destination_is_folded_into_the_outgoing_message():
    # Needed for on-demand fetches from a bare follow-up question ("what
    # does the temperature look like?") that doesn't name a place on its
    # own -- without this, the model has nothing to tell it which city to
    # check.
    response = _mock_tool_response(text="No special context needed.")

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.gather_trip_context("what does the temperature look like?", destination="Austin")

    sent_contents = mock_call.call_args.args[0]
    user_message = sent_contents[0].parts[0].text
    assert "Austin" in user_message
    assert "what does the temperature look like?" in user_message


def test_single_tool_call_executes_and_returns_final_summary():
    tool_call_response = _mock_tool_response(function_calls=[
        _mock_function_call("convert_currency", {"amount": 500, "from_currency": "USD", "to_currency": "ISK"}),
    ])
    final_response = _mock_tool_response(text="500 USD is about 68,500 ISK.")

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", side_effect=[tool_call_response, final_response]),
        patch("app.tools.convert_currency", return_value={"converted": 68500}) as mock_convert,
    ):
        result = agent_service.gather_trip_context("3 days in Reykjavik, budget is 500 USD")

    mock_convert.assert_called_once_with(amount=500, from_currency="USD", to_currency="ISK")
    assert result == "500 USD is about 68,500 ISK."


def test_function_response_is_sent_back_with_user_role_not_tool_role():
    # Confirmed live against the real API: role="tool" is rejected outright
    # ("Role 'tool' is not supported"), despite that being the shape
    # Ollama's /api/chat used. Function-response parts must go back in a
    # role="user" turn.
    tool_call_response = _mock_tool_response(function_calls=[
        _mock_function_call("convert_currency", {"amount": 500, "from_currency": "USD", "to_currency": "ISK"}),
    ])
    final_response = _mock_tool_response(text="done")

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", side_effect=[tool_call_response, final_response]) as mock_call,
        patch("app.tools.convert_currency", return_value={"converted": 68500}),
    ):
        agent_service.gather_trip_context("3 days in Reykjavik, budget is 500 USD")

    # second call's contents: [user turn, model's function-call turn, function-response turn]
    second_call_contents = mock_call.call_args_list[1].args[0]
    assert second_call_contents[-1].role == "user"


def test_unknown_tool_name_does_not_crash_the_loop():
    tool_call_response = _mock_tool_response(function_calls=[_mock_function_call("totally_made_up_tool", {})])
    final_response = _mock_tool_response(text="Proceeding without extra context.")

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", side_effect=[tool_call_response, final_response]),
    ):
        result = agent_service.gather_trip_context("a trip somewhere")

    assert result == "Proceeding without extra context."


def test_network_failure_fails_quietly_and_returns_empty_string():
    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", side_effect=ConnectionError("no route to host")),
    ):
        result = agent_service.gather_trip_context("weekend in Denver")

    assert result == ""


def test_network_failure_is_logged_not_silent(caplog):
    # Regression test (2026-08-31 architecture review, Tier 2): the loop
    # failing quietly to its *caller* (asserted above) used to also mean
    # failing quietly in the logs, with zero signal that anything went
    # wrong at all -- a real problem since these loops are on by default in
    # production. loop_name identifies which of the three loops failed.
    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", side_effect=ConnectionError("no route to host")),
        caplog.at_level("ERROR", logger="app.agent_service"),
    ):
        agent_service.gather_trip_context("weekend in Denver")

    assert any("currency" in r.message and "failed" in r.message for r in caplog.records)


def test_max_tool_rounds_exhaustion_is_logged_not_silent(caplog):
    # A loop that never converges (the model keeps calling tools instead of
    # ever giving a final answer) is a different failure shape from an
    # outright exception -- also worth its own log line, not just silence.
    always_calls_a_tool = _mock_tool_response(function_calls=[_mock_function_call("convert_currency", {})])
    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=always_calls_a_tool),
        patch("app.tools.convert_currency", return_value={"converted": 100}),
        caplog.at_level("WARNING", logger="app.agent_service"),
    ):
        result = agent_service.gather_trip_context("weekend in Denver")

    assert result == ""
    assert any("currency" in r.message and "MAX_TOOL_ROUNDS" in r.message for r in caplog.records)


def test_system_prompt_instructs_against_inventing_data_for_failed_tools():
    # Regression test: a tool returning {"error": ...} was being fed back to
    # the model with no instruction to distinguish "tool failed" from "tool
    # succeeded" -- a weak local model can paper over the failure with a
    # fabricated-sounding summary instead of admitting the data wasn't
    # available.
    assert "error" in agent_service.AGENT_SYSTEM_PROMPT.lower()
    assert "invent" in agent_service.AGENT_SYSTEM_PROMPT.lower()


def test_exceeding_max_rounds_returns_empty_string():
    # A response that keeps requesting the same tool forever should not loop indefinitely.
    infinite_tool_call = _mock_tool_response(function_calls=[
        _mock_function_call("convert_currency", {"amount": 10, "from_currency": "USD", "to_currency": "EUR"}),
    ])

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=infinite_tool_call),
        patch("app.tools.convert_currency", return_value={"converted": 9.2}),
    ):
        result = agent_service.gather_trip_context("endless trip")

    assert result == ""


def test_gather_trip_context_only_exposes_currency_schema():
    # Regression guard for the schema-isolation rule in this module's
    # docstring: gather_trip_context must never advertise get_place_context
    # to the model, or currency's pause would leak an unrelated tool.
    response = _mock_tool_response(text="no context needed")

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.gather_trip_context("weekend in Chicago")

    tool_schema = mock_call.call_args.args[2]
    names = [d.name for d in tool_schema.function_declarations]
    assert names == ["convert_currency"]


# --- answer_question_with_tools (place-context) ---


def test_qa_tools_short_circuits_to_empty_when_disabled():
    with (
        patch("app.agent_service.QA_TOOL_CALLING_ENABLED", False),
        patch("app.agent_service._call_gemini_with_tools") as mock_call,
    ):
        result = agent_service.answer_question_with_tools("tell me about the Louvre", [])

    assert result == ""
    mock_call.assert_not_called()


def test_qa_tools_only_exposes_place_context_schema():
    # Mirrors test_gather_trip_context_only_exposes_currency_schema -- the
    # two loops must never see each other's tool.
    response = _mock_tool_response(text="It's a famous museum in Paris.")

    with (
        patch("app.agent_service.QA_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.answer_question_with_tools("tell me about the Louvre", [])

    tool_schema = mock_call.call_args.args[2]
    names = [d.name for d in tool_schema.function_declarations]
    assert names == ["get_place_context"]


def test_qa_tools_runs_fresh_every_call_no_internal_caching():
    # The key regression test for the once-per-conversation cache bug this
    # loop was built to avoid: two separate calls about two different
    # places must each produce their own real tool call, never reuse the
    # first call's answer. (The actual "don't cache across turns" contract
    # lives in the caller, routers/trips.py -- this proves the function
    # itself has no hidden internal memoization that would undermine that.)
    louvre_call = _mock_tool_response(function_calls=[
        _mock_function_call("get_place_context", {"place_name": "Louvre"}),
    ])
    louvre_final = _mock_tool_response(text="The Louvre is a famous museum in Paris.")
    eiffel_call = _mock_tool_response(function_calls=[
        _mock_function_call("get_place_context", {"place_name": "Eiffel Tower"}),
    ])
    eiffel_final = _mock_tool_response(text="The Eiffel Tower is a landmark in Paris.")

    with (
        patch("app.agent_service.QA_TOOL_CALLING_ENABLED", True),
        patch(
            "app.agent_service._call_gemini_with_tools",
            side_effect=[louvre_call, louvre_final, eiffel_call, eiffel_final],
        ),
        patch("app.tools.get_place_context", side_effect=[
            {"place": "Louvre", "summary": "A museum.", "detail": "brief"},
            {"place": "Eiffel Tower", "summary": "A tower.", "detail": "brief"},
        ]) as mock_tool,
    ):
        first = agent_service.answer_question_with_tools("tell me about the Louvre", [])
        second = agent_service.answer_question_with_tools("what about the Eiffel Tower?", [])

    assert first == "The Louvre is a famous museum in Paris."
    assert second == "The Eiffel Tower is a landmark in Paris."
    assert mock_tool.call_count == 2


def test_qa_tools_builds_contents_from_chat_history_and_new_prompt():
    response = _mock_tool_response(text="Sure.")
    chat_messages = [
        {"role": "user", "content": "planning a trip to Paris"},
        {"role": "assistant", "content": "Great choice! What dates?"},
    ]

    with (
        patch("app.agent_service.QA_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.answer_question_with_tools("tell me about the Louvre", chat_messages)

    sent_contents = mock_call.call_args.args[0]
    assert len(sent_contents) == 3  # 2 history turns + the new question
    assert sent_contents[0].role == "user"
    assert sent_contents[1].role == "model"  # stored "assistant" maps to Gemini's "model"
    assert sent_contents[2].parts[0].text == "tell me about the Louvre"


def test_qa_tools_folds_agent_context_into_system_instruction():
    response = _mock_tool_response(text="Sure.")

    with (
        patch("app.agent_service.QA_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.answer_question_with_tools(
            "what should I pack?", [], agent_context="Forecast: 104-108F, sunny."
        )

    system_instruction = mock_call.call_args.args[1]
    assert "104-108F" in system_instruction


def test_qa_tools_folds_tour_guide_mode_note_into_system_instruction():
    response = _mock_tool_response(text="Sure.")

    with (
        patch("app.agent_service.QA_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.answer_question_with_tools("what else is nearby?", [], tour_guide_mode=True)

    system_instruction = mock_call.call_args.args[1]
    assert "continuing an ongoing tour-guide" in system_instruction
    # 2026-08-29: persistent tour-guide mode no longer forces detail=
    # "detailed" on every later turn (reversed once the fabrication risk
    # that originally motivated it was fixed a different way -- see
    # QA_TOOL_SYSTEM_PROMPT's own anti-invention instruction). It still
    # keeps the persona going and reinforces brief-by-default-unless-asked.
    assert 'detail="brief"' in system_instruction
    assert "own wording explicitly" in system_instruction
    assert "do not carry an earlier message's request for more detail forward" in system_instruction.lower()


def test_qa_tools_omits_tour_guide_mode_note_by_default():
    response = _mock_tool_response(text="Sure.")

    with (
        patch("app.agent_service.QA_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.answer_question_with_tools("what else is nearby?", [])

    system_instruction = mock_call.call_args.args[1]
    assert "continuing an ongoing tour-guide" not in system_instruction


def test_qa_tools_network_failure_fails_quietly():
    with (
        patch("app.agent_service.QA_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", side_effect=ConnectionError("no route to host")),
    ):
        result = agent_service.answer_question_with_tools("tell me about the Louvre", [])

    assert result == ""


def test_qa_system_prompt_instructs_brief_default_and_against_inventing():
    assert "brief" in agent_service.QA_TOOL_SYSTEM_PROMPT.lower()
    assert "error" in agent_service.QA_TOOL_SYSTEM_PROMPT.lower()
    assert "invent" in agent_service.QA_TOOL_SYSTEM_PROMPT.lower()


def test_qa_system_prompt_instructs_against_inventing_specific_venues_in_detailed_mode():
    # Regression test: live-verified that a successful (non-error) tool
    # call in detail="detailed" mode could still get padded with invented-
    # sounding specific business names/addresses not present in the tool
    # result or conversation history (e.g. a fake-sounding "Chef Creole" /
    # "Little Haiti Museum" / exact street numbers for a "be my tour guide"
    # answer) -- the original anti-fabrication instruction only covered the
    # tool-returned-an-error case, not "the tool succeeded but I'm padding
    # the answer with plausible-sounding extras anyway". See docs/sessions/.
    prompt_lower = agent_service.QA_TOOL_SYSTEM_PROMPT.lower()
    assert "venue" in prompt_lower or "specific business" in prompt_lower
    assert "address" in prompt_lower


def test_qa_system_prompt_does_not_treat_be_my_tour_guide_as_a_detail_trigger():
    # Regression test: live-verified that on the activation turn, a bare
    # "be my tour guide" (no specific place named) triggered a full
    # day-by-day recap of the entire already-generated itinerary -- because
    # "be my tour guide" was listed alongside "tell me the full history"/
    # "give me more detail" as a detail="detailed" trigger phrase, so the
    # model treated activating the persona as a request to dump everything
    # it knew about the trip. Fixed by dropping it from that list (the
    # phrase now only affects persona/voice, not detail level) and adding
    # an explicit instruction to give a short welcome instead of a full
    # itinerary recap when no specific place is named.
    prompt = agent_service.QA_TOOL_SYSTEM_PROMPT
    detail_trigger_examples = prompt.split('detail="detailed"')[1].split(").")[0]
    assert "be my tour guide" not in detail_trigger_examples.lower()
    prompt_lower = prompt.lower()
    assert "short, friendly welcome" in prompt_lower or "friendly welcome" in prompt_lower
    assert "without naming a specific place" in prompt_lower


# --- gather_place_context_for_itinerary (place-context, itinerary planning) ---


def test_planning_context_short_circuits_to_empty_when_disabled():
    with (
        patch("app.agent_service.PLANNING_TOOL_CALLING_ENABLED", False),
        patch("app.agent_service._call_gemini_with_tools") as mock_call,
    ):
        result = agent_service.gather_place_context_for_itinerary("5 days in Lisbon")

    assert result == ""
    mock_call.assert_not_called()


def test_planning_context_only_exposes_place_context_schema():
    # Mirrors test_gather_trip_context_only_exposes_currency_schema and
    # test_qa_tools_only_exposes_place_context_schema -- all three loops
    # must never see a tool they don't own.
    response = _mock_tool_response(text="Lisbon is Portugal's hilly, coastal capital.")

    with (
        patch("app.agent_service.PLANNING_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.gather_place_context_for_itinerary("5 days in Lisbon")

    tool_schema = mock_call.call_args.args[2]
    names = [d.name for d in tool_schema.function_declarations]
    assert names == ["get_place_context"]


def test_planning_context_uses_its_own_system_prompt_not_qa_or_currency():
    response = _mock_tool_response(text="Lisbon is Portugal's hilly, coastal capital.")

    with (
        patch("app.agent_service.PLANNING_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.gather_place_context_for_itinerary("5 days in Lisbon")

    system_instruction = mock_call.call_args.args[1]
    assert system_instruction == agent_service.PLANNING_TOOL_SYSTEM_PROMPT
    assert system_instruction != agent_service.QA_TOOL_SYSTEM_PROMPT
    assert system_instruction != agent_service.AGENT_SYSTEM_PROMPT


def test_planning_context_sends_the_raw_prompt_with_no_destination_wrapping():
    # Unlike gather_trip_context, this never receives a separate destination
    # arg (generate_itinerary calls it concurrently with destination
    # inference, before a destination is known) -- the model reads it
    # straight out of the prompt text itself.
    response = _mock_tool_response(text="no context needed")

    with (
        patch("app.agent_service.PLANNING_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", return_value=response) as mock_call,
    ):
        agent_service.gather_place_context_for_itinerary("5 days in Lisbon")

    sent_contents = mock_call.call_args.args[0]
    assert sent_contents[0].parts[0].text == "5 days in Lisbon"


def test_planning_context_network_failure_fails_quietly():
    with (
        patch("app.agent_service.PLANNING_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service._call_gemini_with_tools", side_effect=ConnectionError("no route to host")),
    ):
        result = agent_service.gather_place_context_for_itinerary("5 days in Lisbon")

    assert result == ""


def test_planning_system_prompt_instructs_brief_default_and_against_inventing():
    prompt_lower = agent_service.PLANNING_TOOL_SYSTEM_PROMPT.lower()
    assert "brief" in prompt_lower
    assert "error" in prompt_lower
    assert "invent" in prompt_lower
