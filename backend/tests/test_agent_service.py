from unittest.mock import Mock, patch

from app import agent_service


def _mock_chat_response(message: dict) -> Mock:
    resp = Mock()
    resp.json.return_value = {"message": message}
    resp.raise_for_status = Mock()
    return resp


def test_no_tool_needed_returns_content_directly():
    response = _mock_chat_response({"role": "assistant", "content": "No special context needed for this trip."})

    with patch("app.agent_service.requests.post", return_value=response):
        result = agent_service.gather_trip_context("weekend in Chicago")

    assert result == "No special context needed for this trip."


def test_single_tool_call_executes_and_returns_final_summary():
    tool_call_response = _mock_chat_response({
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "function": {
                "name": "convert_currency",
                "arguments": {"amount": 1000, "from_currency": "USD", "to_currency": "ISK"},
            }
        }],
    })
    final_response = _mock_chat_response({"role": "assistant", "content": "1000 USD is about 137000 ISK."})

    with (
        patch("app.agent_service.requests.post", side_effect=[tool_call_response, final_response]),
        patch("app.tools.convert_currency", return_value={"converted": 137000}) as mock_fx,
    ):
        result = agent_service.gather_trip_context("3 days in Reykjavik, $1000 budget")

    mock_fx.assert_called_once_with(amount=1000, from_currency="USD", to_currency="ISK")
    assert result == "1000 USD is about 137000 ISK."


def test_unknown_tool_name_does_not_crash_the_loop():
    tool_call_response = _mock_chat_response({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "totally_made_up_tool", "arguments": {}}}],
    })
    final_response = _mock_chat_response({"role": "assistant", "content": "Proceeding without extra context."})

    with patch("app.agent_service.requests.post", side_effect=[tool_call_response, final_response]):
        result = agent_service.gather_trip_context("a trip somewhere")

    assert result == "Proceeding without extra context."


def test_network_failure_fails_quietly_and_returns_empty_string():
    with patch("app.agent_service.requests.post", side_effect=ConnectionError("no route to host")):
        result = agent_service.gather_trip_context("weekend in Denver")

    assert result == ""


def test_exceeding_max_rounds_returns_empty_string():
    # A response that keeps requesting the same tool forever should not loop indefinitely.
    infinite_tool_call = _mock_chat_response({
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "function": {
                "name": "convert_currency",
                "arguments": {"amount": 1, "from_currency": "USD", "to_currency": "EUR"},
            }
        }],
    })

    with (
        patch("app.agent_service.requests.post", return_value=infinite_tool_call),
        patch("app.tools.convert_currency", return_value={"converted": 0.9}),
    ):
        result = agent_service.gather_trip_context("endless trip")

    assert result == ""
