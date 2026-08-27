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
