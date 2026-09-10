from datetime import date, timedelta
from types import SimpleNamespace

from app import passport_service


def test_is_trip_completed_true_for_a_real_past_date_range():
    start = date.today() - timedelta(days=10)
    assert passport_service.is_trip_completed(start, total_days=3) is True


def test_is_trip_completed_false_for_a_future_start_date():
    start = date.today() + timedelta(days=5)
    assert passport_service.is_trip_completed(start, total_days=3) is False


def test_is_trip_completed_false_for_a_trip_still_ongoing_today():
    # Started yesterday, runs 3 days -- today is still within the range.
    start = date.today() - timedelta(days=1)
    assert passport_service.is_trip_completed(start, total_days=3) is False


def test_is_trip_completed_false_when_no_start_date_given():
    # Can't prove completion without a real date -- never guessed True.
    assert passport_service.is_trip_completed(None, total_days=5) is False


def test_is_trip_completed_false_when_no_itinerary_days_at_all():
    start = date.today() - timedelta(days=30)
    assert passport_service.is_trip_completed(start, total_days=0) is False


def _fake_trip(trip_id: int, destination: str, start_date: date | None):
    return SimpleNamespace(id=trip_id, destination=destination, start_date=start_date)


def test_deduplicate_stamps_collapses_same_destination_and_same_date():
    same_date = date(2027, 3, 1)
    trips = [
        _fake_trip(1, "Miami", same_date),
        _fake_trip(2, "Miami", same_date),
    ]
    result = passport_service.deduplicate_stamps(trips)
    assert [t.id for t in result] == [1]


def test_deduplicate_stamps_keeps_same_destination_different_dates():
    trips = [
        _fake_trip(1, "Miami", date(2027, 3, 1)),
        _fake_trip(2, "Miami", date(2027, 6, 1)),
    ]
    result = passport_service.deduplicate_stamps(trips)
    assert [t.id for t in result] == [1, 2]


def test_deduplicate_stamps_never_collapses_dateless_trips():
    # No date to compare -- can't tell "same trip asked twice" from "two
    # separate trips," so both are kept, even though they're the same
    # destination and would collapse if dated identically.
    trips = [
        _fake_trip(1, "Miami", None),
        _fake_trip(2, "Miami", None),
    ]
    result = passport_service.deduplicate_stamps(trips)
    assert [t.id for t in result] == [1, 2]


def test_deduplicate_stamps_is_case_and_whitespace_insensitive():
    trips = [
        _fake_trip(1, "Miami", date(2027, 3, 1)),
        _fake_trip(2, " miami ", date(2027, 3, 1)),
    ]
    result = passport_service.deduplicate_stamps(trips)
    assert [t.id for t in result] == [1]


def test_deduplicate_stamps_keeps_different_destinations():
    same_date = date(2027, 3, 1)
    trips = [
        _fake_trip(1, "Miami", same_date),
        _fake_trip(2, "Dallas", same_date),
    ]
    result = passport_service.deduplicate_stamps(trips)
    assert [t.id for t in result] == [1, 2]
