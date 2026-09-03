from datetime import date
from unittest.mock import Mock, patch

from app.clients import ticketmaster_client


def _clear_cache():
    ticketmaster_client.get_event.cache_clear()


def test_search_events_success():
    response = Mock()
    response.json.return_value = {
        "_embedded": {"events": [{"id": "abc123", "name": "Miami Heat vs. Phoenix Suns"}]}
    }

    with patch("app.clients.ticketmaster_client.requests.get", return_value=response) as mock_get:
        result = ticketmaster_client.search_events("Miami", keyword="basketball")

    assert result == [{"id": "abc123", "name": "Miami Heat vs. Phoenix Suns"}]
    params = mock_get.call_args.kwargs["params"]
    assert params["apikey"] == ticketmaster_client.TICKETMASTER_API_KEY
    assert params["city"] == "Miami"
    # classificationName, not keyword -- see search_events' docstring for
    # why: Ticketmaster's `keyword` param does literal name matching and
    # produces real false positives ("jazz" matching "Utah Jazz"),
    # `classificationName` matches its actual genre taxonomy instead.
    assert params["classificationName"] == "basketball"
    assert "keyword" not in params
    assert "startDateTime" not in params  # only included when given


def test_search_events_passes_date_window_when_given():
    response = Mock()
    response.json.return_value = {"_embedded": {"events": []}}

    with patch("app.clients.ticketmaster_client.requests.get", return_value=response) as mock_get:
        ticketmaster_client.search_events("Miami", start_date=date(2026, 9, 12), end_date=date(2026, 9, 17))

    params = mock_get.call_args.kwargs["params"]
    assert params["startDateTime"] == "2026-09-12T00:00:00Z"
    assert params["endDateTime"] == "2026-09-17T23:59:59Z"


def test_search_events_no_results_returns_empty_list():
    response = Mock()
    response.json.return_value = {}  # no "_embedded" key at all -- real shape when nothing matches

    with patch("app.clients.ticketmaster_client.requests.get", return_value=response):
        result = ticketmaster_client.search_events("asdfghjkl")

    assert result == []


def test_search_events_request_failure_returns_empty_list_not_none():
    with patch("app.clients.ticketmaster_client.requests.get", side_effect=Exception("network down")):
        result = ticketmaster_client.search_events("Miami")

    assert result == []


def test_search_events_not_cached_across_calls():
    """Deliberate asymmetry with get_event -- see the module docstring:
    event listings should never be served stale."""
    response = Mock()
    response.json.return_value = {"_embedded": {"events": [{"id": "abc123"}]}}

    with patch("app.clients.ticketmaster_client.requests.get", return_value=response) as mock_get:
        ticketmaster_client.search_events("Miami")
        ticketmaster_client.search_events("Miami")

    assert mock_get.call_count == 2


def test_get_event_success():
    _clear_cache()
    response = Mock()
    response.json.return_value = {"id": "abc123", "name": "Miami Heat vs. Phoenix Suns"}

    with patch("app.clients.ticketmaster_client.requests.get", return_value=response) as mock_get:
        result = ticketmaster_client.get_event("abc123")

    assert result["id"] == "abc123"
    params = mock_get.call_args.kwargs["params"]
    assert params["apikey"] == ticketmaster_client.TICKETMASTER_API_KEY


def test_get_event_request_failure_returns_none():
    _clear_cache()
    with patch("app.clients.ticketmaster_client.requests.get", side_effect=Exception("network down")):
        result = ticketmaster_client.get_event("bad-id")

    assert result is None


def test_get_event_is_cached_across_calls():
    _clear_cache()
    response = Mock()
    response.json.return_value = {"id": "abc123"}

    with patch("app.clients.ticketmaster_client.requests.get", return_value=response) as mock_get:
        ticketmaster_client.get_event("abc123")
        ticketmaster_client.get_event("abc123")

    assert mock_get.call_count == 1  # second call served from lru_cache
