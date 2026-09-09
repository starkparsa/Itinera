from datetime import date

from app.event_planning import (
    extract_committed_event_id,
    extract_event_not_found,
    resolve_start_date_for_event,
)


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


def test_extract_event_not_found_finds_the_marker():
    summary = "Looked for the requested show.\nEVENT_NOT_FOUND: Alex O'Connor\nPlanning a general trip instead."
    assert extract_event_not_found(summary) == "Alex O'Connor"


def test_extract_event_not_found_returns_none_when_absent():
    # The common case -- either no commitment attempt, or one that found
    # a real event (COMMITTED_EVENT_ID fired instead).
    summary = "Found Miami Heat vs. Phoenix Suns on 2027-03-08.\nCOMMITTED_EVENT_ID: abc123"
    assert extract_event_not_found(summary) is None


def test_extract_event_not_found_handles_empty_string():
    assert extract_event_not_found("") is None


def test_extract_event_not_found_handles_none():
    assert extract_event_not_found(None) is None


def test_extract_event_not_found_ignores_mention_without_the_exact_marker():
    # A browsing miss described in ordinary prose must not trigger this --
    # only the exact required marker line counts.
    summary = "I couldn't find any Alex O'Connor shows in New York right now."
    assert extract_event_not_found(summary) is None
