from unittest.mock import Mock, patch

from app.clients import pexels_client


def _clear_cache():
    pexels_client.search_photo.cache_clear()


def test_search_photo_success():
    _clear_cache()
    response = Mock()
    response.json.return_value = {
        "photos": [
            {
                "src": {"large": "https://images.pexels.com/photos/1/lisbon.jpeg"},
                "photographer": "Jane Doe",
                "photographer_url": "https://www.pexels.com/@jane-doe",
            }
        ]
    }

    with patch("app.clients.pexels_client.requests.get", return_value=response) as mock_get:
        result = pexels_client.search_photo("Lisbon")

    assert result == {
        "url": "https://images.pexels.com/photos/1/lisbon.jpeg",
        "photographer": "Jane Doe",
        "photographer_url": "https://www.pexels.com/@jane-doe",
    }
    kwargs = mock_get.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == pexels_client.PEXELS_API_KEY
    assert kwargs["params"] == {"query": "Lisbon", "per_page": 1, "orientation": "landscape"}


def test_search_photo_no_results_returns_none():
    _clear_cache()
    response = Mock()
    response.json.return_value = {"photos": []}

    with patch("app.clients.pexels_client.requests.get", return_value=response):
        result = pexels_client.search_photo("asdfghjkl")

    assert result is None


def test_search_photo_request_failure_returns_none():
    _clear_cache()
    with patch("app.clients.pexels_client.requests.get", side_effect=Exception("network down")):
        result = pexels_client.search_photo("Lisbon")

    assert result is None


def test_search_photo_is_cached_across_calls():
    _clear_cache()
    response = Mock()
    response.json.return_value = {
        "photos": [{"src": {"large": "https://images.pexels.com/photos/1/lisbon.jpeg"}, "photographer": "Jane Doe", "photographer_url": "x"}]
    }

    with patch("app.clients.pexels_client.requests.get", return_value=response) as mock_get:
        pexels_client.search_photo("Lisbon")
        pexels_client.search_photo("Lisbon")

    assert mock_get.call_count == 1  # second call served from lru_cache
