from datetime import date
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

from app import calendar_export
from app.database import Base, engine
from app.main import app

client = TestClient(app)

FAKE_ITINERARY = {
    "destination": "Austin",
    "days": [
        {
            "day_number": 1,
            "items": [
                {"time_of_day": "morning", "activity": "Zilker Park"},
                {"time_of_day": "14:00", "activity": "Barton Springs Pool", "notes": "Bring a towel"},
            ],
        },
        {"day_number": 2, "items": [{"time_of_day": None, "activity": "Free day"}]},
    ],
}


def setup_function():
    # Fresh tables for each test since the shared in-memory SQLite engine
    # persists data across tests otherwise.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def mock_intent_classification():
    with patch("app.llm_service.classify_intent", return_value=("new_trip", False)):
        yield


def _mock_item(day_number=1, time_of_day="morning", activity="Zilker Park", notes=None, item_id=1):
    item = Mock()
    item.id = item_id
    item.day_number = day_number
    item.time_of_day = time_of_day
    item.activity = activity
    item.notes = notes
    return item


# ---------- unit tests: calendar_export.build_trip_calendar / resolve_event_time ----------

def test_day_date_is_start_date_plus_day_number_minus_one():
    item = _mock_item(day_number=3, time_of_day=None)
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), [item])
    cal = Calendar.from_ical(ics_bytes)
    event = next(iter(cal.walk("VEVENT")))
    assert event["dtstart"].dt == date(2026, 9, 3)  # start_date + 2 days


def test_literal_24h_time_is_recognized():
    assert calendar_export.resolve_event_time("14:00") == (14, 0)


def test_literal_12h_time_is_recognized():
    assert calendar_export.resolve_event_time("2pm") == (14, 0)
    assert calendar_export.resolve_event_time("2:30pm") == (14, 30)
    assert calendar_export.resolve_event_time("9am") == (9, 0)


@pytest.mark.parametrize("text,expected", calendar_export.TIME_KEYWORDS)
def test_keyword_times_map_to_expected_hours(text, expected):
    assert calendar_export.resolve_event_time(text) == expected


def test_more_specific_keyword_wins_over_substring():
    assert calendar_export.resolve_event_time("late morning") == (11, 0)
    assert calendar_export.resolve_event_time("morning") == (9, 0)


def test_unrecognized_time_of_day_produces_all_day_event():
    item = _mock_item(time_of_day="flexible")
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), [item])
    event = next(iter(Calendar.from_ical(ics_bytes).walk("VEVENT")))
    assert event["dtstart"].dt == date(2026, 9, 1)  # date, not datetime -- all-day


def test_none_time_of_day_produces_all_day_event():
    item = _mock_item(time_of_day=None)
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), [item])
    event = next(iter(Calendar.from_ical(ics_bytes).walk("VEVENT")))
    assert event["dtstart"].dt == date(2026, 9, 1)


def test_all_day_event_dtend_is_exclusive_next_day():
    item = _mock_item(time_of_day=None)
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), [item])
    event = next(iter(Calendar.from_ical(ics_bytes).walk("VEVENT")))
    assert event["dtend"].dt == date(2026, 9, 2)


def test_timed_event_uses_default_duration():
    item = _mock_item(time_of_day="14:00")
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), [item])
    event = next(iter(Calendar.from_ical(ics_bytes).walk("VEVENT")))
    assert event["dtend"].dt - event["dtstart"].dt == calendar_export.DEFAULT_EVENT_DURATION


def test_uid_is_unique_per_item_and_stable_format():
    items = [_mock_item(item_id=1), _mock_item(item_id=2, day_number=2)]
    ics_bytes = calendar_export.build_trip_calendar(42, "Austin", date(2026, 9, 1), items)
    events = list(Calendar.from_ical(ics_bytes).walk("VEVENT"))
    uids = {str(e["uid"]) for e in events}
    assert len(uids) == 2
    assert all("trip-42-item-" in uid for uid in uids)


def test_summary_location_description_map_correctly():
    item = _mock_item(activity="Barton Springs Pool", notes="Bring a towel")
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), [item])
    event = next(iter(Calendar.from_ical(ics_bytes).walk("VEVENT")))
    assert str(event["summary"]) == "Barton Springs Pool"
    assert str(event["location"]) == "Austin"
    assert str(event["description"]) == "Bring a towel"


def test_notes_absent_when_item_has_no_notes():
    item = _mock_item(notes=None)
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), [item])
    event = next(iter(Calendar.from_ical(ics_bytes).walk("VEVENT")))
    assert "description" not in event


def test_vevent_count_matches_item_count():
    items = [_mock_item(item_id=i, day_number=1) for i in range(3)]
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), items)
    events = list(Calendar.from_ical(ics_bytes).walk("VEVENT"))
    assert len(events) == 3


def test_empty_items_returns_valid_empty_calendar():
    ics_bytes = calendar_export.build_trip_calendar(1, "Austin", date(2026, 9, 1), [])
    cal = Calendar.from_ical(ics_bytes)  # doesn't raise
    assert list(cal.walk("VEVENT")) == []


def test_ics_filename_slugifies_destination():
    assert calendar_export.ics_filename("Paris, France") == "paris-france-itinerary.ics"


# ---------- integration tests: GET /trips/{trip_id}/calendar.ics ----------

def test_export_returns_200_and_ics_content_when_start_date_resolved():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post(
            "/trips/generate", json={"prompt": "weekend in Austin starting 2026-08-30"},
        )
    trip_id = response.json()["trip_id"]

    export_response = client.get(f"/trips/{trip_id}/calendar.ics")

    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("text/calendar")
    assert ".ics" in export_response.headers["content-disposition"]
    assert export_response.content.startswith(b"BEGIN:VCALENDAR")


def test_export_event_count_matches_generated_itinerary_items():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post(
            "/trips/generate", json={"prompt": "weekend in Austin starting 2026-08-30"},
        )
    trip_id = response.json()["trip_id"]

    export_response = client.get(f"/trips/{trip_id}/calendar.ics")

    assert export_response.content.count(b"BEGIN:VEVENT") == 3  # matches FAKE_ITINERARY's 3 items


def test_export_returns_400_when_trip_has_no_start_date():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    trip_id = response.json()["trip_id"]
    assert response.json()["start_date"] is None  # sanity-check the premise

    export_response = client.get(f"/trips/{trip_id}/calendar.ics")

    assert export_response.status_code == 400
    assert "start date" in export_response.json()["detail"].lower()


def test_export_returns_404_for_unknown_trip_id():
    response = client.get("/trips/999999/calendar.ics")
    assert response.status_code == 404
