from unittest.mock import Mock, patch

from app import pexels_service


def _trip(photo_url=None):
    trip = Mock()
    trip.destination = "Lisbon"
    trip.photo_url = photo_url
    trip.photo_credit = None
    trip.photo_fetched_at = None
    return trip


def test_disabled_returns_none_without_a_network_call():
    trip = _trip()
    with (
        patch("app.pexels_service.pexels_client.PEXELS_API_ENABLED", False),
        patch("app.pexels_service.pexels_client.search_photo") as mock_search,
    ):
        result = pexels_service.get_or_refresh_trip_photo(trip)

    assert result is None
    mock_search.assert_not_called()
    assert trip.photo_url is None  # nothing mutated


def test_fetches_and_caches_on_first_call():
    trip = _trip()
    with (
        patch("app.pexels_service.pexels_client.PEXELS_API_ENABLED", True),
        patch(
            "app.pexels_service.pexels_client.search_photo",
            return_value={"url": "https://images.pexels.com/1.jpeg", "photographer": "Jane Doe", "photographer_url": "x"},
        ) as mock_search,
    ):
        result = pexels_service.get_or_refresh_trip_photo(trip)

    assert result == {"url": "https://images.pexels.com/1.jpeg", "credit": "Jane Doe"}
    assert trip.photo_url == "https://images.pexels.com/1.jpeg"
    assert trip.photo_credit == "Jane Doe"
    assert trip.photo_fetched_at is not None
    # The night-skyline query is tried first and succeeded here, so the
    # plain-destination fallback should never even be attempted.
    mock_search.assert_called_once_with("Lisbon city skyline at night")


def test_already_cached_never_refetches_no_ttl():
    # Deliberate deviation from weather's TTL -- see pexels_service's
    # module docstring: a destination's photo doesn't go stale.
    trip = _trip(photo_url="https://images.pexels.com/already-cached.jpeg")
    trip.photo_credit = "Existing Photographer"

    with patch("app.pexels_service.pexels_client.search_photo") as mock_search:
        result = pexels_service.get_or_refresh_trip_photo(trip)

    assert result == {"url": "https://images.pexels.com/already-cached.jpeg", "credit": "Existing Photographer"}
    mock_search.assert_not_called()


def test_search_miss_returns_none_and_does_not_mutate():
    trip = _trip()
    with (
        patch("app.pexels_service.pexels_client.PEXELS_API_ENABLED", True),
        patch("app.pexels_service.pexels_client.search_photo", return_value=None),
    ):
        result = pexels_service.get_or_refresh_trip_photo(trip)

    assert result is None
    assert trip.photo_url is None


def test_falls_back_to_plain_destination_when_no_night_skyline_found():
    # A destination Pexels genuinely has no skyline-style shot for (a
    # small town, a national park) -- the night-skyline query returns
    # nothing, so this should fall back to the plain name rather than
    # leaving the trip with no photo at all.
    trip = _trip()
    trip.destination = "Yellowstone National Park"

    def fake_search(query):
        if "skyline" in query:
            return None
        return {"url": "https://images.pexels.com/yellowstone.jpeg", "photographer": "Jane Doe", "photographer_url": "x"}

    with (
        patch("app.pexels_service.pexels_client.PEXELS_API_ENABLED", True),
        patch("app.pexels_service.pexels_client.search_photo", side_effect=fake_search) as mock_search,
    ):
        result = pexels_service.get_or_refresh_trip_photo(trip)

    assert result == {"url": "https://images.pexels.com/yellowstone.jpeg", "credit": "Jane Doe"}
    assert mock_search.call_args_list == [
        (("Yellowstone National Park city skyline at night",),),
        (("Yellowstone National Park",),),
    ]


def test_returns_none_when_every_query_in_the_priority_list_misses():
    trip = _trip()
    with (
        patch("app.pexels_service.pexels_client.PEXELS_API_ENABLED", True),
        patch("app.pexels_service.pexels_client.search_photo", return_value=None) as mock_search,
    ):
        result = pexels_service.get_or_refresh_trip_photo(trip)

    assert result is None
    assert trip.photo_url is None
    assert mock_search.call_count == 2  # tried both queries, gave up honestly rather than fabricating one
