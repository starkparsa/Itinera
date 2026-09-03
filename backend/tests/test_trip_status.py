from datetime import date, timedelta

from app.trip_status import derive_status


def test_no_start_date_is_draft():
    assert derive_status(start_date=None, day_count=5) == "draft"


def test_start_date_in_the_future_is_upcoming():
    today = date(2026, 9, 3)
    assert derive_status(start_date=today + timedelta(days=8), day_count=5, today=today) == "upcoming"


def test_trip_covering_today_is_upcoming_not_completed():
    today = date(2026, 9, 3)
    # A 5-day trip starting 2 days ago is still running (ends in 2 more days).
    assert derive_status(start_date=today - timedelta(days=2), day_count=5, today=today) == "upcoming"


def test_trip_whose_last_day_was_yesterday_is_completed():
    today = date(2026, 9, 3)
    # A 3-day trip starting 3 days ago ended 1 day ago (start + 2 days = last day).
    assert derive_status(start_date=today - timedelta(days=3), day_count=3, today=today) == "completed"


def test_trip_whose_last_day_is_today_is_still_upcoming():
    today = date(2026, 9, 3)
    # Last day boundary: a 3-day trip starting 2 days ago ends today.
    assert derive_status(start_date=today - timedelta(days=2), day_count=3, today=today) == "upcoming"


def test_zero_day_count_treated_as_a_single_day_not_already_expired():
    today = date(2026, 9, 3)
    # An itinerary with no saved items yet (day_count=0) starting today
    # should not read as already completed.
    assert derive_status(start_date=today, day_count=0, today=today) == "upcoming"


def test_defaults_today_to_date_today_when_omitted():
    # No `today` override -- exercises the real date.today() fallback path.
    far_future = date.today() + timedelta(days=365)
    assert derive_status(start_date=far_future, day_count=5) == "upcoming"
