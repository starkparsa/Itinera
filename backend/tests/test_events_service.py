from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

from app import events_service


def test_no_destination_returns_empty_without_a_call():
    trip = Mock(destination=None, events_json=None, events_fetched_at=None)

    with patch("app.events_service.tools.find_events") as mock_find:
        result = events_service.get_or_refresh_trip_events(trip)

    assert result == []
    mock_find.assert_not_called()


def test_ticketmaster_not_configured_returns_empty():
    trip = Mock(destination="Lisbon", events_json=None, events_fetched_at=None, start_date=None, items=[])

    with patch("app.events_service.tools.find_events", return_value={"error": "Ticketmaster lookup is not configured"}):
        result = events_service.get_or_refresh_trip_events(trip)

    assert result == []


def test_fresh_trip_fetches_once_and_populates_cache_columns():
    trip = Mock(destination="Lisbon", events_json=None, events_fetched_at=None, start_date=None, items=[])
    fake_results = [{"event_id": "1", "name": "Fado Night"}]

    with patch("app.events_service.tools.find_events", return_value={"results": fake_results}) as mock_find:
        result = events_service.get_or_refresh_trip_events(trip)

    mock_find.assert_called_once()
    assert result == fake_results
    assert trip.events_json == '[{"event_id": "1", "name": "Fado Night"}]'
    assert trip.events_fetched_at > datetime.utcnow() - timedelta(seconds=5)


def test_within_ttl_trip_does_not_refetch():
    trip = Mock(
        destination="Lisbon",
        events_json='[{"event_id": "1", "name": "Cached Event"}]',
        events_fetched_at=datetime.utcnow(),
    )

    with patch("app.events_service.tools.find_events") as mock_find:
        result = events_service.get_or_refresh_trip_events(trip)

    mock_find.assert_not_called()
    assert result == [{"event_id": "1", "name": "Cached Event"}]


def test_past_ttl_trip_refetches():
    trip = Mock(
        destination="Lisbon",
        events_json='[{"event_id": "1", "name": "Stale Event"}]',
        events_fetched_at=datetime.utcnow() - timedelta(hours=7),
        start_date=None,
        items=[],
    )
    fresh_results = [{"event_id": "2", "name": "Fresh Event"}]

    with patch("app.events_service.tools.find_events", return_value={"results": fresh_results}) as mock_find:
        result = events_service.get_or_refresh_trip_events(trip)

    mock_find.assert_called_once()
    assert result == fresh_results


def test_find_events_error_returns_empty_not_the_error_string():
    trip = Mock(destination="Nowhereville", events_json=None, events_fetched_at=None, start_date=None, items=[])

    with patch("app.events_service.tools.find_events", return_value={"error": "No events found for 'Nowhereville'"}):
        result = events_service.get_or_refresh_trip_events(trip)

    assert result == []


def test_date_window_spans_the_full_trip_length():
    trip = Mock(
        destination="Lisbon",
        events_json=None,
        events_fetched_at=None,
        start_date=date(2026, 10, 1),
        items=[Mock(day_number=1), Mock(day_number=3)],
    )

    with patch("app.events_service.tools.find_events", return_value={"results": []}) as mock_find:
        events_service.get_or_refresh_trip_events(trip)

    mock_find.assert_called_once_with(city="Lisbon", start_date="2026-10-01", end_date="2026-10-03")


def test_no_items_yet_calls_with_no_end_date():
    trip = Mock(destination="Lisbon", events_json=None, events_fetched_at=None, start_date=date(2026, 10, 1), items=[])

    with patch("app.events_service.tools.find_events", return_value={"results": []}) as mock_find:
        events_service.get_or_refresh_trip_events(trip)

    mock_find.assert_called_once_with(city="Lisbon", start_date="2026-10-01", end_date=None)
