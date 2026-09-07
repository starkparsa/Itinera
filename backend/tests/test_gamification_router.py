from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app

FAKE_ITINERARY = {
    "destination": "Paris",
    "items": [{"day_number": 1, "time_of_day": "Morning", "activity": "Louvre", "notes": None}],
    "agent_context": "",
}

client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_fresh_user_gets_an_empty_passport():
    resp = client.get("/gamification/passport")
    assert resp.status_code == 200
    body = resp.json()
    assert body["level"] == 1
    assert body["xp_points"] == 0
    assert body["trip_count"] == 0
    assert body["stamps"] == []
    assert body["achievements"] == []
    assert body["newly_unlocked"] == []


def test_passport_reflects_a_stamp_and_first_trip_after_generating_a_new_trip():
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]),
    ):
        created = client.post("/trips/generate", json={"prompt": "5 days in Paris"})
    assert created.status_code == 200

    resp = client.get("/gamification/passport")
    body = resp.json()

    assert body["trip_count"] == 1
    assert len(body["stamps"]) == 1
    assert body["stamps"][0]["destination"] == "Paris"
    assert body["newly_unlocked"] == ["first_trip"]
    achievement_codes = {a["code"] for a in body["achievements"]}
    assert "first_trip" in achievement_codes


def test_newly_unlocked_is_not_repeated_on_a_later_visit():
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]),
    ):
        client.post("/trips/generate", json={"prompt": "5 days in Paris"})

    client.get("/gamification/passport")  # first visit sees newly_unlocked
    second = client.get("/gamification/passport")

    assert second.json()["newly_unlocked"] == []
    assert "first_trip" in {a["code"] for a in second.json()["achievements"]}
