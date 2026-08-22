from unittest.mock import Mock, patch

from app import tools


def _geocode_response(*results):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json.return_value = {"results": list(results)}
    return resp


def _forecast_response(dates, highs, lows, pops, codes):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json.return_value = {
        "timezone": "Asia/Tokyo",
        "daily": {
            "time": dates,
            "temperature_2m_max": highs,
            "temperature_2m_min": lows,
            "precipitation_probability_max": pops,
            "weather_code": codes,
        },
    }
    return resp


KYOTO = {
    "name": "Kyoto",
    "latitude": 35.021,
    "longitude": 135.754,
    "country": "Japan",
    "country_code": "JP",
    "admin1": "Kyoto",
    "population": 1_463_723,
}


def test_get_weather_forecast_geocodes_then_fetches_daily():
    geo = _geocode_response(KYOTO)
    forecast = _forecast_response(
        dates=["2026-08-23", "2026-08-24"],
        highs=[32.4, 31.0],
        lows=[24.1, 23.8],
        pops=[20, 55.4],
        codes=[2, 61],
    )

    with patch("app.tools.requests.get", side_effect=[geo, forecast]) as mock_get:
        result = tools.get_weather_forecast("Kyoto", days=2)

    assert result["location"] == "Kyoto"
    assert result["country"] == "Japan"
    assert result["days"][0]["high_c"] == 32.4
    assert result["days"][0]["low_c"] == 24.1
    assert result["days"][0]["precip_chance_pct"] == 20
    assert result["days"][0]["condition"] == "partly cloudy"
    assert result["days"][1]["condition"] == "rain"

    geocode_url = mock_get.call_args_list[0].args[0]
    assert "geocoding-api.open-meteo.com" in geocode_url
    forecast_kwargs = mock_get.call_args_list[1].kwargs
    assert forecast_kwargs["params"]["latitude"] == 35.021
    assert forecast_kwargs["params"]["longitude"] == 135.754
    assert forecast_kwargs["params"]["forecast_days"] == 2


def test_get_weather_forecast_prefers_country_mentioned_in_query():
    paris_tx = {
        "name": "Paris",
        "latitude": 33.66,
        "longitude": -95.55,
        "country": "United States",
        "country_code": "US",
        "admin1": "Texas",
        "population": 9_000_000,  # higher than France so population-only ranking would pick this
    }
    paris_fr = {
        "name": "Paris",
        "latitude": 48.85,
        "longitude": 2.35,
        "country": "France",
        "country_code": "FR",
        "population": 2_138_551,
    }
    geo = _geocode_response(paris_tx, paris_fr)
    forecast = _forecast_response(["2026-08-23"], [22.0], [14.0], [10], [0])

    with patch("app.tools.requests.get", side_effect=[geo, forecast]) as mock_get:
        result = tools.get_weather_forecast("Paris, France", days=1)

    assert result["country"] == "France"
    assert mock_get.call_args_list[1].kwargs["params"]["latitude"] == 48.85


def test_get_weather_forecast_retries_city_part_when_full_string_misses():
    empty = _geocode_response()
    hit = _geocode_response(KYOTO)
    forecast = _forecast_response(["2026-08-23"], [30.0], [22.0], [5], [0])

    with patch("app.tools.requests.get", side_effect=[empty, hit, forecast]) as mock_get:
        result = tools.get_weather_forecast("Kyoto, Japan", days=1)

    assert result["location"] == "Kyoto"
    assert mock_get.call_args_list[0].kwargs["params"]["name"] == "Kyoto, Japan"
    assert mock_get.call_args_list[1].kwargs["params"]["name"] == "Kyoto"


def test_get_weather_forecast_unknown_place():
    with patch("app.tools.requests.get", return_value=_geocode_response()):
        result = tools.get_weather_forecast("Nowhereville")

    assert "error" in result


def test_get_weather_forecast_skips_unknown_destination():
    with patch("app.tools.requests.get") as mock_get:
        result = tools.get_weather_forecast("Unknown")

    assert "error" in result
    mock_get.assert_not_called()


def test_get_weather_forecast_caps_horizon_and_adds_note():
    geo = _geocode_response(KYOTO)
    sixteen_dates = [f"2026-08-{i:02d}" for i in range(1, 17)]
    forecast = _forecast_response(
        dates=sixteen_dates,
        highs=[30.0] * 16,
        lows=[20.0] * 16,
        pops=[10] * 16,
        codes=[0] * 16,
    )

    with patch("app.tools.requests.get", side_effect=[geo, forecast]) as mock_get:
        result = tools.get_weather_forecast("Kyoto", days=30)

    assert mock_get.call_args_list[1].kwargs["params"]["forecast_days"] == 16
    assert "16" in result["note"]
    assert len(result["days"]) == 16


def test_format_weather_context_dates_days_and_marks_horizon():
    forecast = {
        "location": "Kyoto",
        "country": "Japan",
        "days": [
            {"date": "2026-08-23", "high_c": 32.0, "low_c": 24.0, "precip_chance_pct": 20, "condition": "partly cloudy"},
            {"date": "2026-08-24", "high_c": 31.0, "low_c": 23.0, "precip_chance_pct": 55, "condition": "rain"},
        ],
        "note": "Forecast only covers the first 16 days; later days have no reliable forecast.",
    }

    text = tools.format_weather_context(forecast, start_day=1, end_day=3)

    assert "Kyoto, Japan" in text
    assert "Day 1 (2026-08-23)" in text
    assert "24.0–32.0°C" in text
    assert "Day 2 (2026-08-24)" in text
    assert "rain" in text
    assert "Day 3: no forecast available" in text
    assert "16 days" in text


def test_format_weather_context_empty_on_error():
    assert tools.format_weather_context({"error": "nope"}) == ""


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
