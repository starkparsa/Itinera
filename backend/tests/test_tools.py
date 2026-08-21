from unittest.mock import Mock, patch

from app import tools


def test_get_weather_forecast_success():
    geo_response = Mock()
    geo_response.json.return_value = {"results": [{"name": "Kyoto", "country": "Japan", "latitude": 35.0, "longitude": 135.8}]}
    forecast_response = Mock()
    forecast_response.json.return_value = {
        "daily": {
            "temperature_2m_max": [20, 21],
            "temperature_2m_min": [10, 11],
            "precipitation_probability_max": [5, 10],
        }
    }

    with patch("app.tools.requests.get", side_effect=[geo_response, forecast_response]):
        result = tools.get_weather_forecast("Kyoto")

    assert result["location"] == "Kyoto"
    assert result["country"] == "Japan"
    assert result["daily_high_c"] == [20, 21]


def test_get_weather_forecast_unknown_city():
    geo_response = Mock()
    geo_response.json.return_value = {"results": []}

    with patch("app.tools.requests.get", return_value=geo_response):
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
