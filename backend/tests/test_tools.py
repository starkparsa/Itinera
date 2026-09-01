from unittest.mock import Mock, patch

from app import tools


def test_convert_currency_success():
    response = Mock()
    response.json.return_value = {"amount": 100, "base": "USD", "rates": {"EUR": 92.5}}

    with patch("app.tools.requests.get", return_value=response):
        result = tools.convert_currency(100, "usd", "eur")

    assert result["converted"] == 92.5
    assert result["from"] == "USD"
    assert result["to"] == "EUR"


def test_convert_currency_unknown_code():
    response = Mock()
    response.json.return_value = {"amount": 100, "base": "USD", "rates": {}}

    with patch("app.tools.requests.get", return_value=response):
        result = tools.convert_currency(100, "usd", "xyz")

    assert "error" in result


def test_get_place_context_brief_default():
    with patch("app.tools.wikipedia_client.resolve_title", return_value="Eiffel Tower"), \
         patch("app.tools.wikipedia_client.get_summary", return_value="A short summary about the tower."):
        result = tools.get_place_context("eiffel tower")

    assert result["place"] == "Eiffel Tower"
    assert result["detail"] == "brief"
    assert result["summary"] == "A short summary about the tower."


def test_get_place_context_detailed_requires_explicit_flag():
    long_text = "Sentence one. " * 300  # well over both caps
    with patch("app.tools.wikipedia_client.resolve_title", return_value="Eiffel Tower"), \
         patch("app.tools.wikipedia_client.get_full_extract", return_value=long_text) as mock_full, \
         patch("app.tools.wikipedia_client.get_summary") as mock_brief:
        result = tools.get_place_context("eiffel tower", detail="detailed")

    mock_full.assert_called_once()
    mock_brief.assert_not_called()
    assert result["detail"] == "detailed"
    assert len(result["summary"]) <= tools._DETAILED_CHAR_CAP


def test_get_place_context_brief_trims_long_summary():
    long_text = "Sentence one is here. " * 50  # well over the brief cap
    with patch("app.tools.wikipedia_client.resolve_title", return_value="Paris"), \
         patch("app.tools.wikipedia_client.get_summary", return_value=long_text):
        result = tools.get_place_context("paris")

    assert len(result["summary"]) <= tools._BRIEF_CHAR_CAP
    assert result["summary"].endswith(".") or result["summary"].endswith("...")


def test_get_place_context_unresolved_place_returns_error():
    with patch("app.tools.wikipedia_client.resolve_title", return_value=None):
        result = tools.get_place_context("asdfghjkl")

    assert "error" in result


def test_get_place_context_no_summary_returns_error():
    with patch("app.tools.wikipedia_client.resolve_title", return_value="Some Page"), \
         patch("app.tools.wikipedia_client.get_summary", return_value=None):
        result = tools.get_place_context("some page")

    assert "error" in result


def test_get_place_context_unrecognized_detail_normalizes_to_brief():
    with patch("app.tools.wikipedia_client.resolve_title", return_value="Paris"), \
         patch("app.tools.wikipedia_client.get_summary", return_value="Paris is a city."):
        result = tools.get_place_context("paris", detail="everything")

    assert result["detail"] == "brief"


def test_get_place_details_not_configured_returns_error_no_network_call():
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", False), \
         patch("app.tools.google_places_client.text_search") as mock_search:
        result = tools.get_place_details("Eiffel Tower")

    assert "error" in result
    mock_search.assert_not_called()


def test_get_place_details_brief_success():
    match = {"id": "place123", "displayName": {"text": "Eiffel Tower"}, "rating": 4.7}
    details = {
        "id": "place123",
        "displayName": {"text": "Eiffel Tower"},
        "formattedAddress": "Av. Gustave Eiffel, 75007 Paris, France",
        "rating": 4.7,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "types": ["tourist_attraction"],
        "currentOpeningHours": {"openNow": True},
    }
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", True), \
         patch("app.tools.google_places_client.text_search", return_value=match), \
         patch("app.tools.google_places_client.place_details", return_value=details) as mock_details:
        result = tools.get_place_details("eiffel tower")

    mock_details.assert_called_once_with("place123", detail="brief")
    assert result["place"] == "Eiffel Tower"
    assert result["address"] == "Av. Gustave Eiffel, 75007 Paris, France"
    assert result["rating"] == 4.7
    assert result["open_now"] is True
    assert result["summary"] is None  # only populated for detail="detailed"


def test_get_place_details_near_hint_builds_combined_query():
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", True), \
         patch("app.tools.google_places_client.text_search", return_value=None) as mock_search:
        tools.get_place_details("Louvre", near="Paris")

    mock_search.assert_called_once_with("Louvre Paris")


def test_get_place_details_detailed_populates_and_trims_summary():
    long_text = "Sentence one. " * 500  # well over the detailed cap
    match = {"id": "place123", "displayName": {"text": "Eiffel Tower"}}
    details = {
        "id": "place123",
        "displayName": {"text": "Eiffel Tower"},
        "editorialSummary": {"text": long_text},
    }
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", True), \
         patch("app.tools.google_places_client.text_search", return_value=match), \
         patch("app.tools.google_places_client.place_details", return_value=details):
        result = tools.get_place_details("eiffel tower", detail="detailed")

    assert result["summary"] is not None
    assert len(result["summary"]) <= tools._DETAILED_CHAR_CAP


def test_get_place_details_unresolved_place_returns_error():
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", True), \
         patch("app.tools.google_places_client.text_search", return_value=None):
        result = tools.get_place_details("asdfghjkl")

    assert "error" in result


def test_find_nearby_places_not_configured_returns_error_no_network_call():
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", False), \
         patch("app.tools.weather_service.geocode") as mock_geocode:
        result = tools.find_nearby_places("restaurant", near="Paris")

    assert "error" in result
    mock_geocode.assert_not_called()


def test_find_nearby_places_success():
    raw_places = [
        {
            "displayName": {"text": "Le Cafe"},
            "rating": 4.5,
            "formattedAddress": "1 Rue de Rivoli, Paris",
            "priceLevel": "PRICE_LEVEL_MODERATE",
            "currentOpeningHours": {"openNow": True},
        }
    ]
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", True), \
         patch("app.tools.weather_service.geocode", return_value=(48.85, 2.35)), \
         patch("app.tools.google_places_client.nearby_search", return_value=raw_places) as mock_nearby:
        result = tools.find_nearby_places("cafe", near="Paris")

    mock_nearby.assert_called_once_with(48.85, 2.35, "cafe")
    assert result["results"] == [
        {
            "name": "Le Cafe",
            "rating": 4.5,
            "address": "1 Rue de Rivoli, Paris",
            "price_level": "PRICE_LEVEL_MODERATE",
            "open_now": True,
        }
    ]


def test_find_nearby_places_respects_limit():
    raw_places = [{"displayName": {"text": f"Place {i}"}} for i in range(5)]
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", True), \
         patch("app.tools.weather_service.geocode", return_value=(48.85, 2.35)), \
         patch("app.tools.google_places_client.nearby_search", return_value=raw_places):
        result = tools.find_nearby_places("cafe", near="Paris", limit=2)

    assert len(result["results"]) == 2


def test_find_nearby_places_falls_back_to_places_text_search_when_geocode_fails():
    # Regression test for the live-found bug (2026-09-01): Open-Meteo's
    # city-name geocoder fails on landmark-level `near` values (e.g. "the
    # Louvre"); find_nearby_places must resolve a location via Places'
    # own text_search instead of surfacing an error / relying on the model
    # to retry with a different phrasing.
    match = {"id": "place123", "location": {"latitude": 48.86, "longitude": 2.34}}
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", True), \
         patch("app.tools.weather_service.geocode", return_value=None), \
         patch("app.tools.google_places_client.text_search", return_value=match), \
         patch("app.tools.google_places_client.nearby_search", return_value=[]) as mock_nearby:
        result = tools.find_nearby_places("cafe", near="the Louvre")

    mock_nearby.assert_called_once_with(48.86, 2.34, "cafe")
    assert result == {"results": []}


def test_find_nearby_places_error_when_both_geocoders_fail():
    with patch("app.tools.google_places_client.PLACES_API_ENABLED", True), \
         patch("app.tools.weather_service.geocode", return_value=None), \
         patch("app.tools.google_places_client.text_search", return_value=None):
        result = tools.find_nearby_places("cafe", near="Nowhereville")

    assert "error" in result
