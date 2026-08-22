from unittest.mock import Mock, patch

from app import tools


def _fake_openweather_response():
    """A realistic /data/2.5/forecast payload spanning two calendar days,
    with multiple 3-hour entries each -- enough to exercise the daily
    aggregation logic (max/min/pop across entries within the same date)."""
    return {
        "cod": "200",
        "city": {"name": "Kyoto", "country": "JP"},
        "list": [
            {"dt_txt": "2026-08-22 03:00:00", "main": {"temp": 18.0}, "pop": 0.1},
            {"dt_txt": "2026-08-22 12:00:00", "main": {"temp": 24.0}, "pop": 0.3},
            {"dt_txt": "2026-08-22 21:00:00", "main": {"temp": 19.0}, "pop": 0.2},
            {"dt_txt": "2026-08-23 03:00:00", "main": {"temp": 17.0}, "pop": 0.0},
            {"dt_txt": "2026-08-23 12:00:00", "main": {"temp": 26.0}, "pop": 0.05},
        ],
    }


def test_get_weather_forecast_success():
    response = Mock()
    response.json.return_value = _fake_openweather_response()

    with (
        patch("app.tools.OPENWEATHER_API_KEY", "fake-key"),
        patch("app.tools.requests.get", return_value=response),
    ):
        result = tools.get_weather_forecast("Kyoto")

    assert result["location"] == "Kyoto"
    assert result["country"] == "JP"
    # day 1 (Aug 22): temps 18/24/19 -> high 24, low 18; day 2 (Aug 23): 17/26 -> high 26, low 17
    assert result["daily_high_c"] == [24.0, 26.0]
    assert result["daily_low_c"] == [18.0, 17.0]
    assert result["precipitation_chance_pct"] == [30.0, 5.0]


def test_get_weather_forecast_missing_api_key():
    with patch("app.tools.OPENWEATHER_API_KEY", ""):
        result = tools.get_weather_forecast("Kyoto")

    assert "error" in result
    assert "OPENWEATHER_API_KEY" in result["error"]


def test_get_weather_forecast_unknown_city():
    response = Mock()
    response.json.return_value = {"cod": "404", "message": "city not found"}

    with (
        patch("app.tools.OPENWEATHER_API_KEY", "fake-key"),
        patch("app.tools.requests.get", return_value=response),
    ):
        result = tools.get_weather_forecast("Nowhereville")

    assert "error" in result


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
