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
