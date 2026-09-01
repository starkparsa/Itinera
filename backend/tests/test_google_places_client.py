from unittest.mock import Mock, patch

from app.clients import google_places_client


def _clear_caches():
    google_places_client.text_search.cache_clear()
    google_places_client.place_details.cache_clear()


def test_text_search_success():
    _clear_caches()
    response = Mock()
    response.json.return_value = {
        "places": [
            {
                "id": "place123",
                "displayName": {"text": "Eiffel Tower"},
                "formattedAddress": "Av. Gustave Eiffel, 75007 Paris, France",
                "rating": 4.7,
            }
        ]
    }

    with patch("app.clients.google_places_client.requests.post", return_value=response) as mock_post:
        result = google_places_client.text_search("Eiffel Tower")

    assert result["id"] == "place123"
    assert result["displayName"]["text"] == "Eiffel Tower"
    kwargs = mock_post.call_args.kwargs
    assert kwargs["headers"]["X-Goog-Api-Key"] == google_places_client.GOOGLE_PLACES_API_KEY
    assert kwargs["headers"]["X-Goog-FieldMask"] == google_places_client._TEXT_SEARCH_FIELD_MASK
    assert kwargs["json"] == {"textQuery": "Eiffel Tower"}


def test_text_search_no_match_returns_none():
    _clear_caches()
    response = Mock()
    response.json.return_value = {"places": []}

    with patch("app.clients.google_places_client.requests.post", return_value=response):
        result = google_places_client.text_search("asdfghjkl")

    assert result is None


def test_text_search_request_failure_returns_none():
    _clear_caches()
    with patch("app.clients.google_places_client.requests.post", side_effect=Exception("network down")):
        result = google_places_client.text_search("Eiffel Tower")

    assert result is None


def test_place_details_brief_uses_narrow_field_mask():
    _clear_caches()
    response = Mock()
    response.json.return_value = {"id": "place123", "displayName": {"text": "Eiffel Tower"}, "rating": 4.7}

    with patch("app.clients.google_places_client.requests.get", return_value=response) as mock_get:
        result = google_places_client.place_details("place123", detail="brief")

    assert result["id"] == "place123"
    kwargs = mock_get.call_args.kwargs
    assert kwargs["headers"]["X-Goog-FieldMask"] == google_places_client._PLACE_DETAILS_BRIEF_FIELD_MASK
    assert "editorialSummary" not in kwargs["headers"]["X-Goog-FieldMask"]


def test_place_details_detailed_uses_wider_field_mask():
    _clear_caches()
    response = Mock()
    response.json.return_value = {"id": "place123"}

    with patch("app.clients.google_places_client.requests.get", return_value=response) as mock_get:
        google_places_client.place_details("place123", detail="detailed")

    kwargs = mock_get.call_args.kwargs
    field_mask = kwargs["headers"]["X-Goog-FieldMask"]
    assert field_mask == google_places_client._PLACE_DETAILS_DETAILED_FIELD_MASK
    assert "editorialSummary" in field_mask


def test_place_details_request_failure_returns_none():
    _clear_caches()
    with patch("app.clients.google_places_client.requests.get", side_effect=Exception("network down")):
        result = google_places_client.place_details("bad-id")

    assert result is None


def test_nearby_search_success_and_caps_at_five():
    response = Mock()
    response.json.return_value = {"places": [{"id": f"p{i}"} for i in range(8)]}

    with patch("app.clients.google_places_client.requests.post", return_value=response) as mock_post:
        result = google_places_client.nearby_search(48.85, 2.35, "restaurant")

    # The request itself asks Google to cap at 5 -- confirm that request shape.
    body = mock_post.call_args.kwargs["json"]
    assert body["maxResultCount"] == 5
    assert body["includedTypes"] == ["restaurant"]
    # google_places_client returns whatever Google sends back; tools.py is
    # responsible for enforcing the caller's own `limit`.
    assert len(result) == 8


def test_nearby_search_failure_returns_empty_list_not_none():
    with patch("app.clients.google_places_client.requests.post", side_effect=Exception("network down")):
        result = google_places_client.nearby_search(48.85, 2.35, "restaurant")

    assert result == []


def test_nearby_search_not_cached_across_calls():
    """Deliberate asymmetry with text_search/place_details -- see the
    module docstring: nearby results should never be served stale."""
    response = Mock()
    response.json.return_value = {"places": [{"id": "p1"}]}

    with patch("app.clients.google_places_client.requests.post", return_value=response) as mock_post:
        google_places_client.nearby_search(48.85, 2.35, "restaurant")
        google_places_client.nearby_search(48.85, 2.35, "restaurant")

    assert mock_post.call_count == 2
