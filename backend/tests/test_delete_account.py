"""DELETE /auth/account -- explicit user request, 2026-09-09: "the ability
for the user to delete their data completely when they delete their
profile." Mirrors test_ownership_isolation.py's two-user pattern to confirm
the purge is scoped to the caller's own data, never a different user's.
"""
from datetime import datetime
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
    return patch.dict(app.dependency_overrides, {get_current_user: lambda: user})


def test_delete_account_removes_the_user_row():
    user = _make_user("user-a")

    with _act_as(user):
        resp = client.delete("/auth/account")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}

    db = SessionLocal()
    try:
        assert db.query(models.User).filter(models.User.id == user.id).first() is None
    finally:
        db.close()


def test_delete_account_purges_conversations_messages_trips_and_items():
    user = _make_user("user-a")

    with _act_as(user), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = created.json()["conversation_id"]
    trip_id = created.json()["trip_id"]

    with _act_as(user):
        client.delete("/auth/account")

    db = SessionLocal()
    try:
        assert db.query(models.Conversation).filter(models.Conversation.id == conv_id).first() is None
        assert db.query(models.Message).filter(models.Message.conversation_id == conv_id).count() == 0
        assert db.query(models.Trip).filter(models.Trip.id == trip_id).first() is None
        assert db.query(models.ItineraryItem).filter(models.ItineraryItem.trip_id == trip_id).count() == 0
    finally:
        db.close()


def test_delete_account_purges_profile_calendar_credential_stats_and_achievements():
    user = _make_user("user-a")
    db = SessionLocal()
    try:
        db.add(models.UserProfile(user_id=user.id, pace="Balanced"))
        db.add(models.GoogleCalendarCredential(
            user_id=user.id,
            encrypted_access_token="enc-access",
            encrypted_refresh_token="enc-refresh",
            access_token_expires_at=datetime(2027, 1, 1),
        ))
        db.add(models.UserStats(user_id=user.id, xp_points=50))
        db.add(models.UserAchievement(user_id=user.id, code="first_trip"))
        db.commit()
    finally:
        db.close()

    with _act_as(user):
        client.delete("/auth/account")

    db = SessionLocal()
    try:
        assert db.query(models.UserProfile).filter(models.UserProfile.user_id == user.id).first() is None
        assert (
            db.query(models.GoogleCalendarCredential).filter(models.GoogleCalendarCredential.user_id == user.id).first()
            is None
        )
        assert db.query(models.UserStats).filter(models.UserStats.user_id == user.id).first() is None
        assert db.query(models.UserAchievement).filter(models.UserAchievement.user_id == user.id).count() == 0
    finally:
        db.close()


def test_delete_account_purges_a_trip_with_no_conversation_at_all():
    # A legacy orphan (predates the conversation_id link) or any future
    # path that skips routers/conversations.py's own purge -- the
    # conversation loop alone wouldn't touch this.
    user = _make_user("user-a")
    db = SessionLocal()
    try:
        orphan_trip = models.Trip(user_id=user.id, destination="Reykjavik", conversation_id=None)
        db.add(orphan_trip)
        db.commit()
        orphan_trip_id = orphan_trip.id
    finally:
        db.close()

    with _act_as(user):
        client.delete("/auth/account")

    db = SessionLocal()
    try:
        assert db.query(models.Trip).filter(models.Trip.id == orphan_trip_id).first() is None
    finally:
        db.close()


def test_delete_account_never_touches_a_different_users_data():
    user_a = _make_user("user-a")
    user_b = _make_user("user-b")

    with _act_as(user_b), patch("app.llm_service.classify_intent", return_value=("new_trip", False)), patch(
        "app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY,
    ):
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    b_conv_id = created.json()["conversation_id"]
    b_trip_id = created.json()["trip_id"]

    with _act_as(user_a):
        client.delete("/auth/account")

    db = SessionLocal()
    try:
        assert db.query(models.User).filter(models.User.id == user_b.id).first() is not None
        assert db.query(models.Conversation).filter(models.Conversation.id == b_conv_id).first() is not None
        assert db.query(models.Trip).filter(models.Trip.id == b_trip_id).first() is not None
    finally:
        db.close()
