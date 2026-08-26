import time
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app import google_calendar, models
from app.database import Base, SessionLocal, engine

TEST_KEY = Fernet.generate_key().decode()


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _make_user(google_sub="cal-user") -> models.User:
    db = SessionLocal()
    try:
        user = models.User(google_sub=google_sub, email=f"{google_sub}@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


# ---------- encryption ----------

def test_encrypt_decrypt_round_trips(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    ciphertext = google_calendar.encrypt_token("real-refresh-token")
    assert ciphertext != "real-refresh-token"
    assert google_calendar.decrypt_token(ciphertext) == "real-refresh-token"


def test_missing_encryption_key_raises_loudly(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", "")
    with pytest.raises(RuntimeError):
        google_calendar.encrypt_token("x")


# ---------- save_credentials ----------

def test_save_credentials_creates_a_new_row(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    user = _make_user()
    db = SessionLocal()
    try:
        expires_at = int(time.time() + 3600)
        google_calendar.save_credentials(db, user, "access-1", "refresh-1", expires_at)

        row = db.query(models.GoogleCalendarCredential).filter(
            models.GoogleCalendarCredential.user_id == user.id,
        ).first()
        assert row is not None
        assert google_calendar.decrypt_token(row.encrypted_access_token) == "access-1"
        assert google_calendar.decrypt_token(row.encrypted_refresh_token) == "refresh-1"
    finally:
        db.close()


def test_save_credentials_first_time_without_refresh_token_raises(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    user = _make_user()
    db = SessionLocal()
    try:
        expires_at = int(time.time() + 3600)
        with pytest.raises(ValueError):
            google_calendar.save_credentials(db, user, "access-1", None, expires_at)
    finally:
        db.close()


def test_save_credentials_update_keeps_existing_refresh_token_when_none_given(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    user = _make_user()
    db = SessionLocal()
    try:
        expires_at = int(time.time() + 3600)
        google_calendar.save_credentials(db, user, "access-1", "refresh-1", expires_at)

        # Google didn't re-issue a refresh token on this later call -- must
        # not clobber the one already stored.
        new_expires_at = int(time.time() + 7200)
        google_calendar.save_credentials(db, user, "access-2", None, new_expires_at)

        row = db.query(models.GoogleCalendarCredential).filter(
            models.GoogleCalendarCredential.user_id == user.id,
        ).first()
        assert google_calendar.decrypt_token(row.encrypted_access_token) == "access-2"
        assert google_calendar.decrypt_token(row.encrypted_refresh_token) == "refresh-1"
    finally:
        db.close()


# ---------- push_trip_to_calendar ----------

def _make_trip(user: models.User, start_date=None) -> models.Trip:
    db = SessionLocal()
    try:
        trip = models.Trip(user_id=user.id, destination="Austin", prompt="test", start_date=start_date)
        db.add(trip)
        db.flush()
        db.add(models.ItineraryItem(trip_id=trip.id, day_number=1, time_of_day="morning", activity="Zilker Park"))
        db.add(models.ItineraryItem(trip_id=trip.id, day_number=1, time_of_day=None, activity="Free evening"))
        db.commit()
        db.refresh(trip)
        return trip
    finally:
        db.close()


def test_push_trip_to_calendar_raises_not_connected_when_no_credential(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    user = _make_user()
    trip = _make_trip(user, start_date=date(2026, 9, 1))
    db = SessionLocal()
    try:
        with pytest.raises(google_calendar.CalendarNotConnectedError):
            google_calendar.push_trip_to_calendar(db, user, trip)
    finally:
        db.close()


def test_push_trip_to_calendar_creates_one_event_per_item(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    monkeypatch.setenv("AUTH_GOOGLE_ID", "test-client-id")
    monkeypatch.setenv("AUTH_GOOGLE_SECRET", "test-client-secret")
    user = _make_user()
    trip = _make_trip(user, start_date=date(2026, 9, 1))

    db = SessionLocal()
    try:
        # Re-fetch bound to *this* session -- the trip returned by
        # _make_trip is detached (its own session already closed), and
        # push_trip_to_calendar lazy-loads trip.items.
        trip = db.query(models.Trip).filter(models.Trip.id == trip.id).first()

        expires_at = int(time.time() + 3600)
        google_calendar.save_credentials(db, user, "access-1", "refresh-1", expires_at)

        mock_service = MagicMock()
        mock_insert = mock_service.events.return_value.insert
        mock_insert.return_value.execute.return_value = {"id": "evt1"}

        with patch("app.google_calendar.build", return_value=mock_service), patch(
            "app.google_calendar.Credentials",
        ) as mock_credentials_cls, patch(
            "app.google_calendar.weather_service.geocode_timezone", return_value="America/Chicago",
        ):
            mock_creds_instance = MagicMock()
            mock_creds_instance.expired = False
            mock_credentials_cls.return_value = mock_creds_instance

            result = google_calendar.push_trip_to_calendar(db, user, trip)

        assert result == {"events_created": 2}
        assert mock_insert.call_count == 2
    finally:
        db.close()


def test_push_trip_to_calendar_includes_timezone_on_timed_events(monkeypatch):
    # Regression test: Google Calendar's REST API rejects a dateTime event
    # with no timezone at all ("Missing time zone definition for start
    # time"), unlike an .ics file's floating-time DTSTART -- confirmed live.
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    monkeypatch.setenv("AUTH_GOOGLE_ID", "test-client-id")
    monkeypatch.setenv("AUTH_GOOGLE_SECRET", "test-client-secret")
    user = _make_user()
    trip = _make_trip(user, start_date=date(2026, 9, 1))

    db = SessionLocal()
    try:
        trip = db.query(models.Trip).filter(models.Trip.id == trip.id).first()
        expires_at = int(time.time() + 3600)
        google_calendar.save_credentials(db, user, "access-1", "refresh-1", expires_at)

        mock_service = MagicMock()
        mock_insert = mock_service.events.return_value.insert
        mock_insert.return_value.execute.return_value = {"id": "evt1"}

        with patch("app.google_calendar.build", return_value=mock_service), patch(
            "app.google_calendar.Credentials",
        ) as mock_credentials_cls, patch(
            "app.google_calendar.weather_service.geocode_timezone", return_value="America/Chicago",
        ):
            mock_creds_instance = MagicMock()
            mock_creds_instance.expired = False
            mock_credentials_cls.return_value = mock_creds_instance

            google_calendar.push_trip_to_calendar(db, user, trip)

        # First item has time_of_day="morning" -> a timed event.
        timed_call = mock_insert.call_args_list[0]
        assert timed_call.kwargs["body"]["start"]["timeZone"] == "America/Chicago"
        assert timed_call.kwargs["body"]["end"]["timeZone"] == "America/Chicago"

        # Second item has time_of_day=None -> an all-day event, no timeZone.
        all_day_call = mock_insert.call_args_list[1]
        assert "timeZone" not in all_day_call.kwargs["body"]["start"]
        assert "timeZone" not in all_day_call.kwargs["body"]["end"]
    finally:
        db.close()


def test_push_trip_to_calendar_falls_back_to_utc_when_geocoding_fails(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    monkeypatch.setenv("AUTH_GOOGLE_ID", "test-client-id")
    monkeypatch.setenv("AUTH_GOOGLE_SECRET", "test-client-secret")
    user = _make_user()
    trip = _make_trip(user, start_date=date(2026, 9, 1))

    db = SessionLocal()
    try:
        trip = db.query(models.Trip).filter(models.Trip.id == trip.id).first()
        expires_at = int(time.time() + 3600)
        google_calendar.save_credentials(db, user, "access-1", "refresh-1", expires_at)

        mock_service = MagicMock()
        mock_insert = mock_service.events.return_value.insert
        mock_insert.return_value.execute.return_value = {"id": "evt1"}

        with patch("app.google_calendar.build", return_value=mock_service), patch(
            "app.google_calendar.Credentials",
        ) as mock_credentials_cls, patch(
            "app.google_calendar.weather_service.geocode_timezone", return_value=None,
        ):
            mock_creds_instance = MagicMock()
            mock_creds_instance.expired = False
            mock_credentials_cls.return_value = mock_creds_instance

            google_calendar.push_trip_to_calendar(db, user, trip)

        timed_call = mock_insert.call_args_list[0]
        assert timed_call.kwargs["body"]["start"]["timeZone"] == "UTC"
    finally:
        db.close()


def test_push_trip_to_calendar_refreshes_an_expired_token(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    monkeypatch.setenv("AUTH_GOOGLE_ID", "test-client-id")
    monkeypatch.setenv("AUTH_GOOGLE_SECRET", "test-client-secret")
    user = _make_user()
    trip = _make_trip(user, start_date=date(2026, 9, 1))

    db = SessionLocal()
    try:
        trip = db.query(models.Trip).filter(models.Trip.id == trip.id).first()

        # Already expired.
        expires_at = int(time.time() - 3600)
        google_calendar.save_credentials(db, user, "stale-access", "refresh-1", expires_at)

        mock_service = MagicMock()
        mock_service.events.return_value.insert.return_value.execute.return_value = {"id": "evt1"}

        with patch("app.google_calendar.build", return_value=mock_service), patch(
            "app.google_calendar.GoogleAuthRequest",
        ), patch("app.google_calendar.Credentials") as mock_credentials_cls, patch(
            "app.google_calendar.weather_service.geocode_timezone", return_value="America/Chicago",
        ):
            mock_creds_instance = MagicMock()
            mock_creds_instance.token = "fresh-access"
            mock_creds_instance.expiry = datetime.utcnow() + timedelta(hours=1)
            mock_credentials_cls.return_value = mock_creds_instance

            google_calendar.push_trip_to_calendar(db, user, trip)

            mock_creds_instance.refresh.assert_called_once()

        row = db.query(models.GoogleCalendarCredential).filter(
            models.GoogleCalendarCredential.user_id == user.id,
        ).first()
        assert google_calendar.decrypt_token(row.encrypted_access_token) == "fresh-access"
    finally:
        db.close()


def test_push_trip_to_calendar_with_no_start_date_raises_value_error(monkeypatch):
    monkeypatch.setattr(google_calendar, "TOKEN_ENCRYPTION_KEY", TEST_KEY)
    user = _make_user()
    trip = _make_trip(user, start_date=None)
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            google_calendar.push_trip_to_calendar(db, user, trip)
    finally:
        db.close()
