"""Tests for the two hardening fixes in main.py/rate_limit.py: CORS is no
longer a bare wildcard, and POST /trips/generate is rate-limited (the one
route that always costs real LLM spend per call). See docs/security-review.md
for the findings these fix, and app/main.py / app/rate_limit.py for the
rationale.
"""
from unittest.mock import patch

from conftest import TEST_GOOGLE_SUB  # noqa: F401 -- imported for parity with other test files
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app

client = TestClient(app)

FAKE_ITINERARY = {
    "destination": "Austin",
    "days": [{"day_number": 1, "items": [{"time_of_day": "morning", "activity": "Zilker Park"}]}],
}


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_cors_allows_the_configured_frontend_origin():
    # Preflight request, the way a real browser would send one before a
    # cross-origin call -- confirms the configured origin (the default,
    # http://localhost:3000, see main.py's ALLOWED_ORIGINS) is actually
    # reflected back, not silently dropped.
    response = client.options(
        "/conversations",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_an_unlisted_origin():
    # The real bug this replaces: allow_origins=["*"] used to reflect back
    # *any* origin. A page on an unrelated domain should not get this
    # header back at all now.
    response = client.options(
        "/conversations",
        headers={
            "Origin": "https://not-the-real-frontend.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_generate_trip_rate_limit_returns_429_after_the_configured_cap():
    # /trips/generate has its own stricter @limiter.limit("10/minute") (see
    # routers/trips.py) -- exceed it and confirm the 11th call in the same
    # window is rejected rather than silently forwarded to the (mocked) LLM
    # pipeline. TestClient's requests all share one synthetic client
    # address, so they all land in the same rate-limit bucket -- exactly
    # what's needed here.
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        responses = [client.post("/trips/generate", json={"prompt": "weekend in Austin"}) for _ in range(11)]

    assert [r.status_code for r in responses[:10]] == [200] * 10
    assert responses[10].status_code == 429


def test_other_routes_are_not_limited_by_the_stricter_generate_trip_cap():
    # The 10/minute limit is scoped to POST /trips/generate specifically
    # (via its own decorator) -- confirms a burst of calls to a different,
    # unrelated route (still under the generous 100/minute app-wide
    # default) isn't accidentally caught by that stricter limit too.
    responses = [client.get("/conversations") for _ in range(15)]
    assert all(r.status_code == 200 for r in responses)
