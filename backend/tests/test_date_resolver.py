from datetime import date

from app.date_resolver import resolve_trip_start_date

TODAY = date(2026, 8, 25)  # a Tuesday


def test_no_date_signal_returns_none():
    # Must not be fooled by bare numbers like a trip length or a budget --
    # this is the case the whole conservative-extraction design exists for.
    assert resolve_trip_start_date("5 days in Reykjavik, budget is 500 USD", TODAY) is None


def test_today():
    assert resolve_trip_start_date("something today please", TODAY) == TODAY


def test_tomorrow():
    assert resolve_trip_start_date("leaving tomorrow", TODAY) == date(2026, 8, 26)


def test_this_weekend_on_a_weekday():
    # TODAY is a Tuesday -- "this weekend" means the coming Saturday.
    assert resolve_trip_start_date("trip this weekend", TODAY) == date(2026, 8, 29)


def test_this_weekend_when_today_is_saturday():
    saturday = date(2026, 8, 29)
    assert resolve_trip_start_date("trip this weekend", saturday) == saturday


def test_next_weekend_on_a_weekday():
    # TODAY is a Tuesday -- "next weekend" is still the coming Saturday.
    assert resolve_trip_start_date("trip next weekend", TODAY) == date(2026, 8, 29)


def test_next_weekend_when_today_is_saturday_means_the_following_one():
    saturday = date(2026, 8, 29)
    assert resolve_trip_start_date("trip next weekend", saturday) == date(2026, 9, 5)


def test_in_n_days():
    assert resolve_trip_start_date("a trip in 10 days", TODAY) == date(2026, 9, 4)


def test_n_days_from_now():
    # Regression test: confirmed live that only "in N days" was handled --
    # "4 days from now" silently resolved to None, so weather never
    # activated for a trip phrased this way even though the prompt clearly
    # states a real start date.
    assert resolve_trip_start_date("a 4 day trip 4 days from now", TODAY) == date(2026, 8, 29)


def test_n_days_from_today():
    assert resolve_trip_start_date("a trip 3 days from today", TODAY) == date(2026, 8, 28)


def test_n_weeks_from_now():
    assert resolve_trip_start_date("a trip 2 weeks from now", TODAY) == date(2026, 9, 8)


def test_in_n_weeks():
    assert resolve_trip_start_date("a trip in 2 weeks", TODAY) == date(2026, 9, 8)


def test_explicit_month_name_date():
    assert resolve_trip_start_date("5 days in Paris starting September 3rd", TODAY) == date(2026, 9, 3)


def test_explicit_iso_date():
    assert resolve_trip_start_date("trip starting 2026-10-12", TODAY) == date(2026, 10, 12)


def test_explicit_numeric_date():
    assert resolve_trip_start_date("trip starting 9/3", TODAY) == date(2026, 9, 3)


def test_no_signal_at_all_returns_none():
    assert resolve_trip_start_date("a relaxing week in Lisbon, mid-range budget", TODAY) is None
