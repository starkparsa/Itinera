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
    # No date was ever given -- can't prove this trip is done, so it must
    # read as still in progress, never guessed complete.
    assert body["stamps"][0]["in_progress"] is True
    assert body["newly_unlocked"] == ["first_trip"]
    achievement_codes = {a["code"] for a in body["achievements"]}
    assert "first_trip" in achievement_codes


def test_passport_collapses_same_destination_same_date_into_one_stamp():
    with (
        patch("app.llm_service.classify_intent", return_value=("new_trip", False)),
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]),
    ):
        client.post("/trips/generate", json={"prompt": "5 days in Paris starting 2027-03-01"})
        client.post("/trips/generate", json={"prompt": "5 days in Paris starting 2027-03-01"})

    body = client.get("/gamification/passport").json()

    assert len(body["stamps"]) == 1


def test_passport_keeps_same_destination_different_dates_as_separate_stamps():
    with (
        patch("app.llm_service.classify_intent", return_value=("new_trip", False)),
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]),
    ):
        client.post("/trips/generate", json={"prompt": "5 days in Paris starting 2027-03-01"})
        client.post("/trips/generate", json={"prompt": "5 days in Paris starting 2027-06-01"})

    body = client.get("/gamification/passport").json()

    assert len(body["stamps"]) == 2


def test_passport_keeps_dateless_duplicates_of_the_same_destination():
    # No date given on either -- can't tell "the same trip asked twice"
    # from "two separate trips to the same city," so neither is collapsed.
    with (
        patch("app.llm_service.classify_intent", return_value=("new_trip", False)),
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]),
    ):
        client.post("/trips/generate", json={"prompt": "5 days in Paris"})
        client.post("/trips/generate", json={"prompt": "another 5 days in Paris"})

    body = client.get("/gamification/passport").json()

    assert len(body["stamps"]) == 2


def test_passport_stamp_is_not_in_progress_once_the_trip_has_passed():
    # FAKE_ITINERARY's own "items" key is never actually read by
    # routers/trips.py (it reads "days") -- a pre-existing fixture quirk
    # that leaves every other test's trips with zero real ItineraryItem
    # rows, harmlessly, since none of them check total_days. This test
    # needs a real day count to compute a real end date, so it uses a
    # correctly-shaped fixture instead of the shared one.
    real_itinerary = {
        "destination": "Paris",
        "days": [{"day_number": 1, "items": [{"time_of_day": "Morning", "activity": "Louvre"}]}],
        "agent_context": "",
    }
    with (
        patch("app.llm_service.classify_intent", return_value=("new_trip", False)),
        patch("app.llm_service.generate_itinerary", return_value=real_itinerary),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]),
    ):
        client.post("/trips/generate", json={"prompt": "1 day in Paris starting 2020-01-01"})

    body = client.get("/gamification/passport").json()

    assert body["stamps"][0]["in_progress"] is False


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
