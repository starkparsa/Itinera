import json
from unittest.mock import patch

import pytest

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
