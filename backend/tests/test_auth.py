from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

from app import auth, models
from app.database import Base, SessionLocal, engine

SECRET = "test-secret"


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _token(
    sub: str | None = "google-sub-1",
    email: str | None = "user@example.com",
    secret: str = SECRET,
    expired: bool = False,
    provider: str | None = None,
) -> str:
    payload = {"email": email}
    if sub is not None:
        payload["sub"] = sub
    if provider is not None:
        payload["provider"] = provider
    payload["exp"] = datetime.utcnow() + (timedelta(seconds=-60) if expired else timedelta(seconds=60))
    return jwt.encode(payload, secret, algorithm=auth.ALGORITHM)


def test_valid_token_returns_correct_user(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        user = auth.get_current_user(authorization=f"Bearer {_token()}", db=db)
        assert user.google_sub == "google-sub-1"
        assert user.email == "user@example.com"
    finally:
        db.close()


def test_unknown_google_sub_auto_provisions_a_user(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        assert db.query(models.User).count() == 0
        user = auth.get_current_user(authorization=f"Bearer {_token(sub='new-sub')}", db=db)
        assert user.id is not None
        assert db.query(models.User).filter(models.User.google_sub == "new-sub").count() == 1
    finally:
        db.close()


def test_second_request_reuses_the_same_user(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        first = auth.get_current_user(authorization=f"Bearer {_token(sub='same-sub')}", db=db)
        db.commit()
        second = auth.get_current_user(authorization=f"Bearer {_token(sub='same-sub')}", db=db)
        assert first.id == second.id
    finally:
        db.close()


def test_missing_authorization_header_raises_401(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(authorization=None, db=db)
        assert exc_info.value.status_code == 401
    finally:
        db.close()


def test_non_bearer_authorization_raises_401(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(authorization="Basic abc123", db=db)
        assert exc_info.value.status_code == 401
    finally:
        db.close()


def test_expired_token_raises_401(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(authorization=f"Bearer {_token(expired=True)}", db=db)
        assert exc_info.value.status_code == 401
    finally:
        db.close()


def test_wrong_secret_raises_401(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        bad_token = _token(secret="a-completely-different-secret")
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(authorization=f"Bearer {bad_token}", db=db)
        assert exc_info.value.status_code == 401
    finally:
        db.close()


def test_token_missing_subject_claim_raises_401(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(authorization=f"Bearer {_token(sub=None)}", db=db)
        assert exc_info.value.status_code == 401
    finally:
        db.close()


def test_credentials_provider_looks_up_by_internal_user_id(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        existing = models.User(email="pw-user@example.com", password_hash="irrelevant-for-this-test")
        db.add(existing)
        db.commit()
        db.refresh(existing)

        token = _token(sub=str(existing.id), email=existing.email, provider="credentials")
        user = auth.get_current_user(authorization=f"Bearer {token}", db=db)
        assert user.id == existing.id
    finally:
        db.close()


def test_credentials_provider_never_auto_provisions(monkeypatch):
    # Unlike Google, a credentials-provider subject that doesn't match any
    # existing user must 401, never silently create one -- an email/
    # password account can only come from /auth/register.
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        assert db.query(models.User).count() == 0
        token = _token(sub="99999", provider="credentials")
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(authorization=f"Bearer {token}", db=db)
        assert exc_info.value.status_code == 401
        assert db.query(models.User).count() == 0
    finally:
        db.close()


def test_credentials_provider_rejects_a_non_numeric_subject(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        token = _token(sub="not-a-number", provider="credentials")
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(authorization=f"Bearer {token}", db=db)
        assert exc_info.value.status_code == 401
    finally:
        db.close()


def test_absent_provider_claim_defaults_to_google_behavior(monkeypatch):
    # Tokens minted before the provider claim existed (or any client still
    # built against the old shape) must keep working unchanged.
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", SECRET)
    db = SessionLocal()
    try:
        user = auth.get_current_user(authorization=f"Bearer {_token(sub='legacy-sub')}", db=db)
        assert user.google_sub == "legacy-sub"
    finally:
        db.close()


def test_unconfigured_secret_raises_500_not_silently_accepting(monkeypatch):
    # A missing AUTH_BACKEND_SECRET must fail loudly -- never be treated as
    # "auth is off" and accept any token.
    monkeypatch.setattr(auth, "AUTH_BACKEND_SECRET", "")
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(authorization=f"Bearer {_token()}", db=db)
        assert exc_info.value.status_code == 500
    finally:
        db.close()
