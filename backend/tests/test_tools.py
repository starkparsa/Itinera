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
