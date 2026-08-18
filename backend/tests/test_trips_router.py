from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app

client = TestClient(app)

FAKE_ITINERARY = {
    "destination": "Austin",
    "days": [
        {"day_number": 1, "items": [{"time_of_day": "morning", "activity": "Zilker Park"}]}
    ],
}


def setup_function():
    # Fresh tables for each test since the shared in-memory SQLite engine
    # persists data across tests otherwise.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_generate_trip_creates_placeholder_user_and_saves_trip():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    assert response.status_code == 200
    body = response.json()
    assert body["destination"] == "Austin"
    assert body["itinerary"][0]["activity"] == "Zilker Park"


def test_generate_trip_reuses_existing_user_on_second_call():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
        second = client.post("/trips/generate", json={"prompt": "week in Austin"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["trip_id"] != second.json()["trip_id"]


def test_generate_trip_forwards_requested_days_to_llm_service():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY) as mock_generate:
        client.post("/trips/generate", json={"prompt": "a month in Japan", "days": 30})

    mock_generate.assert_called_once_with("a month in Japan", requested_days=30)


def test_generate_trip_surfaces_note_from_llm_result():
    result_with_note = {**FAKE_ITINERARY, "note": "Requested 100 days exceeds the 60-day limit; showing the first 60 days."}
    with patch("app.llm_service.generate_itinerary", return_value=result_with_note):
        response = client.post("/trips/generate", json={"prompt": "100 day trip", "days": 100})

    assert response.json()["note"] == result_with_note["note"]
