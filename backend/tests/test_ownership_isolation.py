"""Phase C: every endpoint that reads/writes a specific trip or conversation
must be scoped to the authenticated caller's own data (see CLAUDE.md
decision log, "Auth" row -- an audit found five endpoints with no ownership
check at all before this). These tests simulate two different users by
swapping FastAPI's dependency override for get_current_user mid-test,
confirming a captured id from one user's data is invisible to the other.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import models
from app.auth import get_current_user
from app.database import Base, SessionLocal, engine
from app.main import app

client = TestClient(app)

FAKE_ITINERARY = {
    "destination": "Austin",
    "days": [{"day_number": 1, "items": [{"time_of_day": "morning", "activity": "Zilker Park"}]}],
}


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _make_user(google_sub: str) -> models.User:
    db = SessionLocal()
    try:
        user = models.User(google_sub=google_sub, email=f"{google_sub}@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _act_as(user: models.User):
    """Overrides get_current_user for the duration of a `with` block --
    layered on top of conftest.py's own autouse override, so this always
    wins for calls made inside the block, and is restored on exit."""
    return patch.dict(app.dependency_overrides, {get_current_user: lambda: user})


def test_get_trip_404s_for_a_different_user():
    user_a = _make_user("user-a")
    user_b = _make_user("user-b")

    with _act_as(user_a), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    trip_id = created.json()["trip_id"]

    with _act_as(user_a):
        assert client.get(f"/trips/{trip_id}").status_code == 200
    with _act_as(user_b):
        assert client.get(f"/trips/{trip_id}").status_code == 404


def test_calendar_export_404s_for_a_different_user():
    user_a = _make_user("user-a")
    user_b = _make_user("user-b")

    with _act_as(user_a), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin starting 2026-09-01"})
    trip_id = created.json()["trip_id"]

    with _act_as(user_a):
        assert client.get(f"/trips/{trip_id}/calendar.ics").status_code == 200
    with _act_as(user_b):
        assert client.get(f"/trips/{trip_id}/calendar.ics").status_code == 404


def test_get_conversation_404s_for_a_different_user():
    user_a = _make_user("user-a")
    user_b = _make_user("user-b")

    with _act_as(user_a), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = created.json()["conversation_id"]

    with _act_as(user_a):
        assert client.get(f"/conversations/{conv_id}").status_code == 200
    with _act_as(user_b):
        assert client.get(f"/conversations/{conv_id}").status_code == 404


def test_delete_conversation_404s_for_a_different_user_and_leaves_it_intact():
    user_a = _make_user("user-a")
    user_b = _make_user("user-b")

    with _act_as(user_a), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = created.json()["conversation_id"]

    with _act_as(user_b):
        assert client.delete(f"/conversations/{conv_id}").status_code == 404

    # Untouched -- the owner can still see it.
    with _act_as(user_a):
        assert client.get(f"/conversations/{conv_id}").status_code == 200


def test_list_conversations_only_shows_the_callers_own():
    user_a = _make_user("user-a")
    user_b = _make_user("user-b")

    with _act_as(user_a), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    with _act_as(user_b), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        client.post("/trips/generate", json={"prompt": "weekend in Miami"})

    with _act_as(user_a):
        titles_a = {c["title"] for c in client.get("/conversations").json()}
    with _act_as(user_b):
        titles_b = {c["title"] for c in client.get("/conversations").json()}

    assert titles_a == {"weekend in Austin"}
    assert titles_b == {"weekend in Miami"}


def test_trip_request_body_no_longer_accepts_a_user_id_field():
    # Regression guard for the Phase C removal -- a client-supplied user_id
    # must have no effect at all now, not even silently ignored in a way
    # that could regress back to being read somewhere.
    user_a = _make_user("user-a")
    user_b = _make_user("user-b")

    with _act_as(user_a), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        # Attempting to impersonate user_b via the request body.
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin", "user_id": user_b.id})

    with _act_as(user_a):
        assert client.get(f"/trips/{created.json()['trip_id']}").status_code == 200
    with _act_as(user_b):
        # If user_id in the body still had any effect, this trip would
        # belong to user_b instead and this would be 200.
        assert client.get(f"/trips/{created.json()['trip_id']}").status_code == 404
