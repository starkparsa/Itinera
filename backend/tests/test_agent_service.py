from unittest.mock import Mock, patch

from app import agent_service


def _mock_chat_response(message: dict) -> Mock:
    resp = Mock()
    resp.json.return_value = {"message": message}
    resp.raise_for_status = Mock()
    return resp


def test_agent_step_is_paused_by_default_and_makes_no_network_call():
    # The agent tool-calling step (weather + currency) is currently paused --
    # weather was removed outright after proving unreliable, and currency
    # was paused alongside it rather than leaving a half-working step
    # running. gather_trip_context must short-circuit to "" without touching
    # the network at all while paused.
    with patch("app.agent_service.requests.post") as mock_post:
        result = agent_service.gather_trip_context("weekend in Chicago")

    assert result == ""
    mock_post.assert_not_called()


def test_no_tool_needed_returns_content_directly():
    response = _mock_chat_response({"role": "assistant", "content": "No special context needed for this trip."})

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service.requests.post", return_value=response),
    ):
        result = agent_service.gather_trip_context("weekend in Chicago")

    assert result == "No special context needed for this trip."


def test_destination_is_folded_into_the_outgoing_message():
    # Needed for on-demand fetches from a bare follow-up question ("what
    # does the temperature look like?") that doesn't name a place on its
    # own -- without this, the model has nothing to tell it which city to
    # check.
    response = _mock_chat_response({"role": "assistant", "content": "No special context needed."})

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service.requests.post", return_value=response) as mock_post,
    ):
        agent_service.gather_trip_context("what does the temperature look like?", destination="Austin")

    sent_messages = mock_post.call_args.kwargs["json"]["messages"]
    user_message = next(m["content"] for m in sent_messages if m["role"] == "user")
    assert "Austin" in user_message
    assert "what does the temperature look like?" in user_message


def test_single_tool_call_executes_and_returns_final_summary():
    tool_call_response = _mock_chat_response({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "convert_currency", "arguments": {
            "amount": 500, "from_currency": "USD", "to_currency": "ISK",
        }}}],
    })
    final_response = _mock_chat_response({"role": "assistant", "content": "500 USD is about 68,500 ISK."})

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service.requests.post", side_effect=[tool_call_response, final_response]),
        patch("app.tools.convert_currency", return_value={"converted": 68500}) as mock_convert,
    ):
        result = agent_service.gather_trip_context("3 days in Reykjavik, budget is 500 USD")

    mock_convert.assert_called_once_with(amount=500, from_currency="USD", to_currency="ISK")
    assert result == "500 USD is about 68,500 ISK."


def test_unknown_tool_name_does_not_crash_the_loop():
    tool_call_response = _mock_chat_response({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "totally_made_up_tool", "arguments": {}}}],
    })
    final_response = _mock_chat_response({"role": "assistant", "content": "Proceeding without extra context."})

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service.requests.post", side_effect=[tool_call_response, final_response]),
    ):
        result = agent_service.gather_trip_context("a trip somewhere")

    assert result == "Proceeding without extra context."


def test_network_failure_fails_quietly_and_returns_empty_string():
    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service.requests.post", side_effect=ConnectionError("no route to host")),
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
    infinite_tool_call = _mock_chat_response({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "convert_currency", "arguments": {
            "amount": 10, "from_currency": "USD", "to_currency": "EUR",
        }}}],
    })

    with (
        patch("app.agent_service.AGENT_TOOL_CALLING_ENABLED", True),
        patch("app.agent_service.requests.post", return_value=infinite_tool_call),
        patch("app.tools.convert_currency", return_value={"converted": 9.2}),
    ):
        result = agent_service.gather_trip_context("endless trip")

    assert result == ""
