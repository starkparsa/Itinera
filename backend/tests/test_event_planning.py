from datetime import date

from app.event_planning import extract_committed_event_id, resolve_start_date_for_event


def test_resolve_start_date_defaults_to_two_days_before():
    assert resolve_start_date_for_event(date(2026, 9, 20)) == date(2026, 9, 18)


def test_resolve_start_date_respects_custom_settle_in_days():
    assert resolve_start_date_for_event(date(2026, 9, 20), settle_in_days=1) == date(2026, 9, 19)


def test_extract_committed_event_id_finds_the_marker():
    summary = "Found a great show.\nCOMMITTED_EVENT_ID: abc123\nBuild the trip around it."
    assert extract_committed_event_id(summary) == "abc123"


def test_extract_committed_event_id_returns_none_when_absent():
    # The common/default case -- a browsing question never gets the marker.
    summary = "There are a few jazz shows in Miami this week, including one at Blue Note."
    assert extract_committed_event_id(summary) is None


def test_extract_committed_event_id_handles_empty_string():
    assert extract_committed_event_id("") is None


def test_extract_committed_event_id_handles_none():
    assert extract_committed_event_id(None) is None


def test_extract_committed_event_id_ignores_mention_without_the_exact_marker():
    # Regression guard: the model mentioning an event id in passing prose
    # must NOT be treated as a commitment -- only the exact required
    # marker line counts.
    summary = "The event id is abc123 if you want to look it up yourself."
    assert extract_committed_event_id(summary) is None
