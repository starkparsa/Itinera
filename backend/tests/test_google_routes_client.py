from unittest.mock import Mock, patch

from app.clients import google_routes_client


def test_compute_route_success():
    response = Mock()
    response.json.return_value = {"routes": [{"duration": "1530s", "distanceMeters": 4200}]}

    with patch("app.clients.google_routes_client.requests.post", return_value=response) as mock_post:
        result = google_routes_client.compute_route("the Louvre, Paris", "Notre-Dame, Paris", travel_mode="WALK")

    assert result == {"duration_seconds": 1530, "distance_meters": 4200}
    kwargs = mock_post.call_args.kwargs
    assert kwargs["headers"]["X-Goog-Api-Key"] == google_routes_client.GOOGLE_ROUTES_API_KEY
    assert kwargs["headers"]["X-Goog-FieldMask"] == google_routes_client._FIELD_MASK
    assert kwargs["json"] == {
        "origin": {"address": "the Louvre, Paris"},
        "destination": {"address": "Notre-Dame, Paris"},
        "travelMode": "WALK",
    }


def test_compute_route_no_routes_returns_none():
    response = Mock()
    response.json.return_value = {"routes": []}

    with patch("app.clients.google_routes_client.requests.post", return_value=response):
        result = google_routes_client.compute_route("Nowhere", "Nowhere Else")

    assert result is None


def test_compute_route_request_failure_returns_none():
    with patch("app.clients.google_routes_client.requests.post", side_effect=Exception("network down")):
        result = google_routes_client.compute_route("A", "B")

    assert result is None


def test_compute_route_missing_fields_returns_none():
    # A malformed/partial response (e.g. a TRANSIT route with no distance)
    # must degrade to None, not raise or return a half-populated dict.
    response = Mock()
    response.json.return_value = {"routes": [{"duration": "600s"}]}  # no distanceMeters

    with patch("app.clients.google_routes_client.requests.post", return_value=response):
        result = google_routes_client.compute_route("A", "B")

    assert result is None


def test_compute_route_unparseable_duration_returns_none():
    response = Mock()
    response.json.return_value = {"routes": [{"duration": "not-a-duration", "distanceMeters": 100}]}

    with patch("app.clients.google_routes_client.requests.post", return_value=response):
        result = google_routes_client.compute_route("A", "B")

    assert result is None
