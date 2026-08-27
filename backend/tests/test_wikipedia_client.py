from unittest.mock import Mock, patch

from app.clients import wikipedia_client


def _clear_caches():
    wikipedia_client.resolve_title.cache_clear()
    wikipedia_client.get_summary.cache_clear()
    wikipedia_client.get_full_extract.cache_clear()


def test_resolve_title_success():
    _clear_caches()
    response = Mock()
    response.json.return_value = ["louvre", ["Louvre", "Louvre Palace"], ["", ""], ["", ""]]

    with patch("app.clients.wikipedia_client.requests.get", return_value=response) as mock_get:
        result = wikipedia_client.resolve_title("louvre")

    assert result == "Louvre"
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["User-Agent"] == wikipedia_client.USER_AGENT


def test_resolve_title_appends_near_hint():
    _clear_caches()
    response = Mock()
    response.json.return_value = ["eiffel tower paris", ["Eiffel Tower"], [""], [""]]

    with patch("app.clients.wikipedia_client.requests.get", return_value=response) as mock_get:
        wikipedia_client.resolve_title("eiffel tower", near="paris")

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["search"] == "eiffel tower paris"


def test_resolve_title_no_match_returns_none():
    _clear_caches()
    response = Mock()
    response.json.return_value = ["asdfghjkl", [], [], []]

    with patch("app.clients.wikipedia_client.requests.get", return_value=response):
        result = wikipedia_client.resolve_title("asdfghjkl")

    assert result is None


def test_resolve_title_request_failure_returns_none():
    _clear_caches()
    with patch("app.clients.wikipedia_client.requests.get", side_effect=Exception("network down")):
        result = wikipedia_client.resolve_title("paris")

    assert result is None


def test_get_summary_success():
    _clear_caches()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"extract": "The Eiffel Tower is a lattice tower in Paris."}

    with patch("app.clients.wikipedia_client.requests.get", return_value=response):
        result = wikipedia_client.get_summary("Eiffel Tower")

    assert result == "The Eiffel Tower is a lattice tower in Paris."


def test_get_summary_404_returns_none_not_exception():
    _clear_caches()
    response = Mock()
    response.status_code = 404

    with patch("app.clients.wikipedia_client.requests.get", return_value=response):
        result = wikipedia_client.get_summary("Nonexistent Page Xyz")

    assert result is None


def test_get_full_extract_success():
    _clear_caches()
    response = Mock()
    response.json.return_value = {
        "query": {"pages": [{"title": "Eiffel Tower", "extract": "A much longer article body here." * 20}]}
    }

    with patch("app.clients.wikipedia_client.requests.get", return_value=response):
        result = wikipedia_client.get_full_extract("Eiffel Tower")

    assert result is not None
    assert len(result) > 300


def test_get_full_extract_no_pages_returns_none():
    _clear_caches()
    response = Mock()
    response.json.return_value = {"query": {"pages": []}}

    with patch("app.clients.wikipedia_client.requests.get", return_value=response):
        result = wikipedia_client.get_full_extract("Nonexistent Page Xyz")

    assert result is None
