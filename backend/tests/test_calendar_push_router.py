import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import google_calendar
from app.database import Base, engine
from app.main import app

client = TestClient(app)

FAKE_ITINERARY = {
    "destination": "Austin",
    "days": [{"day_number": 1, "items": [{"time_of_day": "morning", "activity": "Zilker Park"}]}],
}


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _generate_a_trip(prompt="weekend in Austin starting 2026-09-01"):
    with patch("app.llm_service.classify_intent", return_value="new_trip"), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        response = client.post("/trips/generate", json={"prompt": prompt})
    return response.json()


def test_save_google_calendar_token_then_status_reports_connected(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", "unused-because-mocked-below")
    with patch("app.google_calendar.save_credentials") as mock_save:
        res = client.post(
            "/auth/google-calendar-token",
            json={"access_token": "a", "refresh_token": "r", "expires_at": int(time.time() + 3600)},
        )
    assert res.status_code == 200
    mock_save.assert_called_once()


def test_google_calendar_status_defaults_to_not_connected():
    res = client.get("/auth/google-calendar-status")
    assert res.status_code == 200
    assert res.json() == {"connected": False}


def test_push_to_calendar_returns_428_when_not_connected():
    trip = _generate_a_trip()
    res = client.post(f"/trips/{trip['trip_id']}/push-to-calendar")
    assert res.status_code == 428


def test_push_to_calendar_returns_400_when_trip_has_no_start_date():
    trip = _generate_a_trip(prompt="weekend in Austin")  # no date phrase
    assert trip["start_date"] is None
    res = client.post(f"/trips/{trip['trip_id']}/push-to-calendar")
    assert res.status_code == 400


def test_push_to_calendar_returns_404_for_a_different_users_trip():
    from app import models
    from app.auth import get_current_user
    from app.database import SessionLocal

    trip = _generate_a_trip()

    db = SessionLocal()
    try:
        other_user = models.User(google_sub="someone-else", email="someone-else@example.com")
        db.add(other_user)
        db.commit()
        db.refresh(other_user)
    finally:
        db.close()

    with patch.dict(app.dependency_overrides, {get_current_user: lambda: other_user}):
        res = client.post(f"/trips/{trip['trip_id']}/push-to-calendar")
    assert res.status_code == 404


def test_push_to_calendar_succeeds_when_connected():
    trip = _generate_a_trip()

    with patch(
        "app.routers.trips.google_calendar.push_trip_to_calendar", return_value={"events_created": 3},
    ) as mock_push:
        res = client.post(f"/trips/{trip['trip_id']}/push-to-calendar")

    assert res.status_code == 200
    assert res.json() == {"events_created": 3}
    mock_push.assert_called_once()


def test_push_to_calendar_maps_http_error_to_502():
    from googleapiclient.errors import HttpError

    trip = _generate_a_trip()

    fake_response = MagicMock(status=500, reason="Internal error")
    http_error = HttpError(fake_response, b"error body")
    http_error.reason = "Internal error"

    with patch("app.routers.trips.google_calendar.push_trip_to_calendar", side_effect=http_error):
        res = client.post(f"/trips/{trip['trip_id']}/push-to-calendar")

    assert res.status_code == 502
