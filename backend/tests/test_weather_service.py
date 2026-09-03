from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

from app import tools, weather_service


def test_weather_is_not_registered_as_a_gemini_tool():
    # Deliberate design choice (see weather_service.py's module docstring):
    # this feature always runs the same way for every trip, it's never a
    # judgment call the model makes, so it must not cost any Gemini tokens.
    assert "get_daily_forecast" not in tools.TOOL_FUNCTIONS
    assert "geocode" not in tools.TOOL_FUNCTIONS
    assert len(tools.TOOL_SCHEMAS.function_declarations) == 5  # currency + get_place_context + get_place_details + find_nearby_places + find_events


def test_geocode_success():
    response = Mock()
    response.json.return_value = {"results": [{"latitude": 64.1466, "longitude": -21.9426}]}

    with patch("app.weather_service.requests.get", return_value=response):
        result = weather_service.geocode("Reykjavik")

    assert result == (64.1466, -21.9426)


def test_geocode_no_match_returns_none():
    response = Mock()
    response.json.return_value = {"results": []}

    with patch("app.weather_service.requests.get", return_value=response):
        assert weather_service.geocode("Nowhereville") is None


def test_geocode_network_failure_returns_none():
    with patch("app.weather_service.requests.get", side_effect=ConnectionError("no route to host")):
        assert weather_service.geocode("Reykjavik") is None


def test_geocode_timezone_success():
    response = Mock()
    response.json.return_value = {
        "results": [{"latitude": 25.77427, "longitude": -80.19366, "timezone": "America/New_York"}],
    }

    with patch("app.weather_service.requests.get", return_value=response):
        assert weather_service.geocode_timezone("Miami") == "America/New_York"


def test_geocode_timezone_no_match_returns_none():
    response = Mock()
    response.json.return_value = {"results": []}

    with patch("app.weather_service.requests.get", return_value=response):
        assert weather_service.geocode_timezone("Nowhereville") is None


def test_geocode_timezone_network_failure_returns_none():
    with patch("app.weather_service.requests.get", side_effect=ConnectionError("no route to host")):
        assert weather_service.geocode_timezone("Miami") is None


def test_get_daily_forecast_success_maps_wmo_code_to_text():
    response = Mock()
    response.json.return_value = {
        "daily": {
            "time": ["2026-08-26", "2026-08-27"],
            "temperature_2m_max": [22.1, 19.4],
            "temperature_2m_min": [14.2, 12.8],
            "weather_code": [0, 61],
        }
    }

    with patch("app.weather_service.requests.get", return_value=response):
        result = weather_service.get_daily_forecast(64.1, -21.9, date(2026, 8, 26), 2)

    assert result == [
        {
            "day_offset": 0, "date": "2026-08-26", "temp_min": 14.2, "temp_max": 22.1,
            "temp_min_f": 57.6, "temp_max_f": 71.8, "condition": "Clear sky",
        },
        {
            "day_offset": 1, "date": "2026-08-27", "temp_min": 12.8, "temp_max": 19.4,
            "temp_min_f": 55.0, "temp_max_f": 66.9, "condition": "Slight rain",
        },
    ]


def test_get_daily_forecast_fahrenheit_is_real_arithmetic_not_a_guess():
    response = Mock()
    response.json.return_value = {
        "daily": {
            "time": ["2026-08-26"],
            "temperature_2m_max": [0.0],
            "temperature_2m_min": [-40.0],
            "weather_code": [3],
        }
    }

    with patch("app.weather_service.requests.get", return_value=response):
        result = weather_service.get_daily_forecast(64.1, -21.9, date(2026, 8, 26), 1)

    assert result[0]["temp_max_f"] == 32.0  # 0C is exactly 32F
    assert result[0]["temp_min_f"] == -40.0  # -40 is the one point C and F agree


def test_get_daily_forecast_beyond_horizon_returns_empty():
    response = Mock()
    response.json.return_value = {}  # Open-Meteo returns no "daily" block outside its forecast horizon

    with patch("app.weather_service.requests.get", return_value=response):
        result = weather_service.get_daily_forecast(64.1, -21.9, date(2026, 8, 26), 20)

    assert result == []


def test_get_daily_forecast_zero_days_returns_empty_without_a_call():
    with patch("app.weather_service.requests.get") as mock_get:
        result = weather_service.get_daily_forecast(64.1, -21.9, date(2026, 8, 26), 0)

    assert result == []
    mock_get.assert_not_called()


def test_get_daily_forecast_network_failure_returns_empty():
    with patch("app.weather_service.requests.get", side_effect=ConnectionError("no route to host")):
        assert weather_service.get_daily_forecast(64.1, -21.9, date(2026, 8, 26), 3) == []


def test_get_or_refresh_trip_weather_no_start_date_returns_empty():
    trip = Mock(start_date=None, weather_json=None, weather_fetched_at=None)
    assert weather_service.get_or_refresh_trip_weather(trip, [Mock(day_number=1)]) == []


def test_get_or_refresh_trip_weather_no_items_returns_empty():
    trip = Mock(start_date=date(2026, 8, 26), weather_json=None, weather_fetched_at=None)
    assert weather_service.get_or_refresh_trip_weather(trip, []) == []


def test_get_or_refresh_trip_weather_uses_fresh_cache_without_a_network_call():
    trip = Mock(
        start_date=date(2026, 8, 26),
        weather_json='[{"day_number": 1, "date": "2026-08-26", "temp_min": 10, "temp_max": 20, "condition": "Clear sky"}]',
        weather_fetched_at=datetime.utcnow(),
    )

    with patch("app.weather_service.geocode") as mock_geocode:
        result = weather_service.get_or_refresh_trip_weather(trip, [Mock(day_number=1)])

    mock_geocode.assert_not_called()
    assert result[0]["condition"] == "Clear sky"


def test_get_or_refresh_trip_weather_refetches_when_stale():
    trip = Mock(
        start_date=date(2026, 8, 26),
        weather_json='[{"day_number": 1, "date": "2026-08-26", "temp_min": 10, "temp_max": 20, "condition": "stale"}]',
        weather_fetched_at=datetime.utcnow() - timedelta(hours=4),
    )
    items = [Mock(day_number=1)]
    fresh_forecast = [{
        "day_offset": 0, "date": "2026-08-26", "temp_min": 11, "temp_max": 21,
        "temp_min_f": 51.8, "temp_max_f": 69.8, "condition": "Overcast",
    }]

    with (
        patch("app.weather_service.geocode", return_value=(64.1, -21.9)) as mock_geocode,
        patch("app.weather_service.get_daily_forecast", return_value=fresh_forecast) as mock_forecast,
    ):
        result = weather_service.get_or_refresh_trip_weather(trip, items)

    mock_geocode.assert_called_once()
    mock_forecast.assert_called_once()
    assert result == [{
        "day_number": 1, "date": "2026-08-26", "temp_min": 11, "temp_max": 21,
        "temp_min_f": 51.8, "temp_max_f": 69.8, "condition": "Overcast",
    }]
    assert trip.weather_fetched_at > datetime.utcnow() - timedelta(seconds=5)


def test_read_cached_weather_returns_parsed_json_with_no_network_call():
    trip = Mock(
        weather_json='[{"day_number": 1, "date": "2026-08-26", "temp_min": 10, "temp_max": 20, "condition": "Clear sky"}]',
    )

    with patch("app.weather_service.requests.get") as mock_get:
        result = weather_service.read_cached_weather(trip)

    mock_get.assert_not_called()
    assert result == [{"day_number": 1, "date": "2026-08-26", "temp_min": 10, "temp_max": 20, "condition": "Clear sky"}]


def test_read_cached_weather_stale_cache_still_returned_unrefreshed():
    # Unlike get_or_refresh_trip_weather, this never checks staleness at
    # all -- callers that want a freshness check use that function instead
    # (see routers/conversations.py, which only does that for a
    # conversation's most recently generated trip).
    trip = Mock(
        weather_json='[{"day_number": 1, "date": "2026-08-26", "temp_min": 10, "temp_max": 20, "condition": "stale"}]',
        weather_fetched_at=datetime.utcnow() - timedelta(days=30),
    )
    assert weather_service.read_cached_weather(trip)[0]["condition"] == "stale"


def test_read_cached_weather_no_cache_returns_empty_list():
    trip = Mock(weather_json=None)
    assert weather_service.read_cached_weather(trip) == []


def test_summarize_for_prompt_includes_both_units_and_condition():
    weather = [
        {"day_number": 1, "date": "2026-08-26", "temp_min": 25.0, "temp_max": 40.0, "temp_min_f": 77.0, "temp_max_f": 104.0, "condition": "Overcast"},
        {"day_number": 2, "date": "2026-08-27", "temp_min": 29.0, "temp_max": 42.0, "temp_min_f": 84.0, "temp_max_f": 108.0, "condition": "Mainly clear"},
    ]

    summary = weather_service.summarize_for_prompt("Austin", weather)

    assert "Austin" in summary
    assert "Day 1" in summary and "Day 2" in summary
    assert "104" in summary and "40" in summary  # both F and C present
    assert "108" in summary and "42" in summary
    assert "overcast" in summary.lower()


def test_summarize_for_prompt_empty_list_returns_empty_string():
    assert weather_service.summarize_for_prompt("Austin", []) == ""


def test_get_or_refresh_trip_weather_geocode_failure_returns_empty_without_crashing():
    trip = Mock(start_date=date(2026, 8, 26), weather_json=None, weather_fetched_at=None)

    with patch("app.weather_service.geocode", return_value=None):
        result = weather_service.get_or_refresh_trip_weather(trip, [Mock(day_number=1)])

    assert result == []
