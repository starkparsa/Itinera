import json
from unittest.mock import Mock, patch

import pytest
import requests

from app import llm_service


@pytest.fixture(autouse=True)
def mock_agent_context():
    # Every test in this file exercises the itinerary pipeline in isolation.
    # Without this, generate_itinerary's call to agent_service.gather_trip_context
    # would make a real network call to Ollama's /api/chat during tests.
    with patch("app.llm_service.agent_service.gather_trip_context", return_value=""):
        yield


def _mock_ollama_sequence(responses):
    """Returns a function that yields each response in order on successive
    calls to _call_ollama -- lets tests simulate the meta call followed by
    however many chunk calls a trip needs."""
    responses_iter = iter(responses)

    def _fake_call(prompt, num_predict, num_ctx=8192):
        return next(responses_iter)

    return _fake_call


def test_short_trip_makes_one_meta_call_and_one_chunk_call():
    meta = json.dumps({"destination": "Kyoto", "total_days": 3})
    chunk = json.dumps({"days": [
        {"day_number": 1, "items": [{"time_of_day": "morning", "activity": "Fushimi Inari"}]},
        {"day_number": 2, "items": [{"time_of_day": "morning", "activity": "Arashiyama"}]},
        {"day_number": 3, "items": [{"time_of_day": "morning", "activity": "Nishiki Market"}]},
    ]})

    with patch("app.llm_service._call_ollama", side_effect=_mock_ollama_sequence([meta, chunk])):
        result = llm_service.generate_itinerary("3 days in Kyoto")

    assert result["destination"] == "Kyoto"
    assert len(result["days"]) == 3
    assert result["days"][0]["items"][0]["activity"] == "Fushimi Inari"


def test_long_trip_is_split_into_multiple_chunk_calls():
    # 12 days at CHUNK_SIZE_DAYS=5 should produce 3 chunk calls (5, 5, 2).
    meta = json.dumps({"destination": "Italy", "total_days": 12})
    chunk1 = json.dumps({"days": [{"day_number": i, "items": [{"activity": f"Day {i} activity"}]} for i in range(1, 6)]})
    chunk2 = json.dumps({"days": [{"day_number": i, "items": [{"activity": f"Day {i} activity"}]} for i in range(6, 11)]})
    chunk3 = json.dumps({"days": [{"day_number": i, "items": [{"activity": f"Day {i} activity"}]} for i in range(11, 13)]})

    with patch("app.llm_service._call_ollama", side_effect=_mock_ollama_sequence([meta, chunk1, chunk2, chunk3])) as mock_call:
        result = llm_service.generate_itinerary("12 days touring Italy")

    assert len(result["days"]) == 12
    assert result["days"][-1]["day_number"] == 12
    assert mock_call.call_count == 4  # 1 meta call + 3 chunk calls


def test_explicit_requested_days_overrides_model_inference():
    meta = json.dumps({"destination": "Peru", "total_days": 7})  # model guesses wrong
    chunk1 = json.dumps({"days": [{"day_number": i, "items": [{"activity": "hike"}]} for i in range(1, 6)]})
    chunk2 = json.dumps({"days": [{"day_number": i, "items": [{"activity": "hike"}]} for i in range(6, 11)]})

    with patch("app.llm_service._call_ollama", side_effect=_mock_ollama_sequence([meta, chunk1, chunk2])):
        result = llm_service.generate_itinerary("trip to Peru", requested_days=10)

    assert len(result["days"]) == 10


def test_requested_days_beyond_cap_is_clamped_with_note():
    meta = json.dumps({"destination": "World Tour", "total_days": 7})
    # MAX_TOTAL_DAYS=60 -> 12 chunk calls of 5 days each
    chunks = [json.dumps({"days": [{"day_number": i, "items": [{"activity": "explore"}]} for i in range(s, min(s + 5, 61))]}) for s in range(1, 61, 5)]

    with patch("app.llm_service._call_ollama", side_effect=_mock_ollama_sequence([meta, *chunks])):
        result = llm_service.generate_itinerary("a 100 day round the world trip", requested_days=100)

    assert len(result["days"]) == 60
    assert "note" in result
    assert "60" in result["note"]


def test_invalid_meta_json_falls_back_to_defaults():
    chunk1 = json.dumps({"days": [{"day_number": i, "items": [{"activity": "explore"}]} for i in range(1, 6)]})
    chunk2 = json.dumps({"days": [{"day_number": i, "items": [{"activity": "explore"}]} for i in range(6, 8)]})

    with patch("app.llm_service._call_ollama", side_effect=_mock_ollama_sequence(["not json", chunk1, chunk2])):
        result = llm_service.generate_itinerary("somewhere vague")

    assert result["destination"] == "Unknown"
    assert len(result["days"]) == 7  # DEFAULT_TOTAL_DAYS


def test_truncated_chunk_response_raises_clear_error():
    meta = json.dumps({"destination": "Austin", "total_days": 3})
    truncated_chunk = '{"days": [{"day_number": 1, "items": [{"activity": "Zilker'

    with patch("app.llm_service._call_ollama", side_effect=_mock_ollama_sequence([meta, truncated_chunk])):
        try:
            llm_service.generate_itinerary("weekend in Austin")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "cut off" in str(exc)


def test_agent_context_is_surfaced_in_result_and_prompt():
    meta = json.dumps({"destination": "Reykjavik", "total_days": 3})
    chunk = json.dumps({"days": [{"day_number": i, "items": [{"activity": "sightsee"}]} for i in range(1, 4)]})

    captured_prompts = []

    def _fake_call(prompt, num_predict, num_ctx=8192):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with (
        patch("app.llm_service.agent_service.gather_trip_context", return_value="Expect near-freezing temps; pack layers."),
        patch("app.llm_service._call_ollama", side_effect=_fake_call),
    ):
        result = llm_service.generate_itinerary("3 days in Reykjavik")

    assert result["agent_context"] == "Expect near-freezing temps; pack layers."
    # the context should have been folded into the chunk prompt (2nd call)
    assert "near-freezing" in captured_prompts[1]


def test_call_ollama_connection_error_has_actionable_message():
    # Regression test: a raw "Connection refused" (or similar) exception
    # used to be surfaced to the user verbatim in the 502 response, with no
    # hint of what to actually do about it. This is the most common cause
    # in practice -- Ollama simply isn't running.
    with (
        patch("app.llm_service.requests.post", side_effect=requests.exceptions.ConnectionError("Connection refused")),
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service.generate_itinerary("3 days in Reykjavik")

    assert "ollama serve" in str(exc_info.value)


def test_call_ollama_404_hints_model_not_pulled():
    # A 404 from Ollama's /api/generate almost always means the configured
    # model was never pulled -- the message should say so directly instead
    # of just restating "404 Client Error".
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "404 Client Error", response=mock_response,
    )

    with (
        patch("app.llm_service.requests.post", return_value=mock_response),
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service.generate_itinerary("3 days in Reykjavik")

    assert "ollama pull" in str(exc_info.value)


def test_answer_question_translates_connection_error():
    with (
        patch("app.llm_service.requests.post", side_effect=requests.exceptions.ConnectionError("Connection refused")),
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service.answer_question("what's the weather like?", [])

    message = str(exc_info.value)
    assert message.startswith("Failed to answer question:")  # preserves the existing contract
    assert "ollama serve" in message


def test_cached_agent_context_skips_the_agent_step_entirely():
    meta = json.dumps({"destination": "Reykjavik", "total_days": 3})
    chunk = json.dumps({"days": [{"day_number": i, "items": [{"activity": "sightsee"}]} for i in range(1, 4)]})

    with (
        patch("app.llm_service.agent_service.gather_trip_context") as mock_gather,
        patch("app.llm_service._call_ollama", side_effect=_mock_ollama_sequence([meta, chunk])),
    ):
        result = llm_service.generate_itinerary(
            "3 days in Reykjavik", cached_agent_context="Already known: expect snow.",
        )

    mock_gather.assert_not_called()  # the whole point of caching -- no network round-trip
    assert result["agent_context"] == "Already known: expect snow."


# ---------- intent classification ----------

def test_classify_intent_new_trip():
    with patch("app.llm_service._call_ollama", return_value=json.dumps({"intent": "new_trip"})):
        assert llm_service.classify_intent("plan me a trip to Peru", "") == "new_trip"


def test_classify_intent_off_topic():
    with patch("app.llm_service._call_ollama", return_value=json.dumps({"intent": "off_topic"})):
        assert llm_service.classify_intent("write me a sorting algorithm", "") == "off_topic"


def test_classify_intent_question():
    with patch("app.llm_service._call_ollama", return_value=json.dumps({"intent": "question"})):
        assert llm_service.classify_intent("what's the weather like there?", "trip to Kyoto discussed") == "question"


def test_classify_intent_invalid_category_falls_back_to_new_trip():
    with patch("app.llm_service._call_ollama", return_value=json.dumps({"intent": "something_made_up"})):
        assert llm_service.classify_intent("plan a trip", "") == "new_trip"


def test_classify_intent_failure_fails_open_to_new_trip():
    with patch("app.llm_service._call_ollama", side_effect=ConnectionError("unreachable")):
        assert llm_service.classify_intent("plan a trip", "") == "new_trip"


# ---------- conversational Q&A path ----------

def test_answer_question_returns_model_content():
    mock_response = Mock()
    mock_response.json.return_value = {"message": {"content": "It should be sunny and warm in June."}}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response):
        result = llm_service.answer_question("what's the weather like?", [{"role": "user", "content": "trip to Kyoto"}])

    assert result == "It should be sunny and warm in June."


def test_answer_question_raises_on_failure():
    with patch("app.llm_service.requests.post", side_effect=ConnectionError("unreachable")):
        try:
            llm_service.answer_question("what's the weather like?", [])
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "Failed to answer" in str(exc)


def test_answer_question_grounds_the_model_in_real_agent_findings():
    # Regression test: temperature/weather questions were being answered with
    # invented numbers because the real forecast (agent_context) was fetched
    # once during generation and shown in the UI, but never made it into the
    # prompt for follow-up questions -- the model had nothing real to draw on
    # and made something up. The real findings must reach the system prompt.
    mock_response = Mock()
    mock_response.json.return_value = {"message": {"content": "Highs around 24C, per the forecast."}}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response) as mock_post:
        llm_service.answer_question(
            "what's the temperature there?", [], agent_context="Kyoto: highs of 22-26C, low rain chance.",
        )

    sent_system_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "Kyoto: highs of 22-26C" in sent_system_prompt
    assert "invent" in sent_system_prompt.lower()  # instructed not to fabricate numbers


def test_answer_question_instructs_model_not_to_volunteer_agent_context():
    # Regression test: cached agent_context (weather/currency findings from
    # turn 1) was being surfaced unconditionally on every later question in
    # the conversation, so the model kept bringing up weather even on
    # unrelated questions ("what's a good day-3 restaurant area?"). The
    # system prompt must explicitly tell it to only use the data when the
    # question is actually about it.
    mock_response = Mock()
    mock_response.json.return_value = {"message": {"content": "Try the east side for dinner."}}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response) as mock_post:
        llm_service.answer_question(
            "what's a good area for dinner?", [], agent_context="Kyoto: highs of 22-26C, low rain chance.",
        )

    sent_system_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "not proactively mention" in sent_system_prompt.lower()


def test_answer_question_without_agent_context_still_works():
    # No findings cached yet (e.g. first message in a conversation is a
    # question) -- should behave exactly as before, no crash, no empty note.
    mock_response = Mock()
    mock_response.json.return_value = {"message": {"content": "I'd need a destination to check that."}}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response) as mock_post:
        result = llm_service.answer_question("what's the temperature there?", [])

    sent_system_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert sent_system_prompt == llm_service.QUESTION_SYSTEM_PROMPT
    assert result == "I'd need a destination to check that."


def test_answer_question_instructs_honesty_even_with_no_agent_context():
    # Regression test: a weather question with nothing cached yet (no prior
    # trip generation, or the agent step found nothing) got zero grounding
    # AND zero instruction not to guess -- the model just fabricated a
    # confident-sounding forecast (wrong units, invented conditions like
    # "sunny" that don't even exist in the tool's data shape). The base
    # system prompt must forbid guessing real-time facts unconditionally,
    # not just when real data happens to be available.
    mock_response = Mock()
    mock_response.json.return_value = {"message": {"content": "I don't have current data for that."}}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response) as mock_post:
        llm_service.answer_question("what does the temperature look like?", [], agent_context="")

    sent_system_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "do not have live access" in sent_system_prompt.lower()
    assert "don't have current data" in sent_system_prompt.lower()


def test_answer_question_forbids_inventing_units_or_conditions_not_given():
    # Regression test for the exact bug: real agent_context had Celsius
    # numbers only, but the model answered in Fahrenheit with invented sky
    # conditions ("Partly cloudy") that were never part of the data.
    mock_response = Mock()
    mock_response.json.return_value = {"message": {"content": "Highs around 24C, per the forecast."}}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response) as mock_post:
        llm_service.answer_question(
            "what's the temperature there?", [], agent_context="Kyoto: highs of 22-26C, low rain chance.",
        )

    sent_system_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "fahrenheit" in sent_system_prompt.lower()
    assert "sunny" in sent_system_prompt.lower() or "cloudy" in sent_system_prompt.lower()
