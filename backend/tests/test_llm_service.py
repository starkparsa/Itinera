import json
from unittest.mock import patch, Mock

from app import llm_service


def test_generate_itinerary_parses_json():
    fake_payload = {
        "destination": "Kyoto",
        "days": [{"day_number": 1, "items": [{"time_of_day": "morning", "activity": "Fushimi Inari", "notes": "Go early"}]}],
    }
    mock_response = Mock()
    mock_response.json.return_value = {"response": json.dumps(fake_payload)}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response):
        result = llm_service.generate_itinerary("3 days in Kyoto")

    assert result["destination"] == "Kyoto"
    assert result["days"][0]["items"][0]["activity"] == "Fushimi Inari"


def test_generate_itinerary_strips_markdown_fences():
    fake_payload = {"destination": "Rome", "days": []}
    fenced = "```json\n" + json.dumps(fake_payload) + "\n```"
    mock_response = Mock()
    mock_response.json.return_value = {"response": fenced}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response):
        result = llm_service.generate_itinerary("weekend in Rome")

    assert result["destination"] == "Rome"


def test_generate_itinerary_raises_on_invalid_json():
    mock_response = Mock()
    mock_response.json.return_value = {"response": "not json at all"}
    mock_response.raise_for_status = Mock()

    with patch("app.llm_service.requests.post", return_value=mock_response):
        try:
            llm_service.generate_itinerary("anywhere")
            assert False, "expected ValueError"
        except ValueError:
            pass
