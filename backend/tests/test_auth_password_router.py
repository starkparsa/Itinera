from fastapi.testclient import TestClient

from app import models
from app.database import Base, SessionLocal, engine
from app.main import app

client = TestClient(app)

VALID_PASSWORD = "Correct-Horse9"


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_register_creates_an_account():
    resp = client.post("/auth/register", json={"email": "jordan@example.com", "password": VALID_PASSWORD})
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "jordan@example.com"
    assert "id" in body
    assert "password" not in body and "password_hash" not in body


def test_register_lowercases_the_email():
    resp = client.post("/auth/register", json={"email": "Jordan@Example.com", "password": VALID_PASSWORD})
    assert resp.json()["email"] == "jordan@example.com"


def test_register_rejects_a_duplicate_email():
    client.post("/auth/register", json={"email": "jordan@example.com", "password": VALID_PASSWORD})
    resp = client.post("/auth/register", json={"email": "jordan@example.com", "password": VALID_PASSWORD})
    assert resp.status_code == 409


def test_register_rejects_an_invalid_email():
    resp = client.post("/auth/register", json={"email": "not-an-email", "password": VALID_PASSWORD})
    assert resp.status_code == 422


def test_register_rejects_a_too_short_password():
    resp = client.post("/auth/register", json={"email": "jordan@example.com", "password": "Sh0rt!"})
    assert resp.status_code == 422


def test_register_rejects_a_password_missing_an_uppercase_letter():
    resp = client.post("/auth/register", json={"email": "jordan@example.com", "password": "lowercase9!"})
    assert resp.status_code == 422


def test_register_rejects_a_password_missing_a_number():
    resp = client.post("/auth/register", json={"email": "jordan@example.com", "password": "NoNumbers!"})
    assert resp.status_code == 422


def test_register_rejects_a_password_missing_a_special_character():
    resp = client.post("/auth/register", json={"email": "jordan@example.com", "password": "NoSpecial9"})
    assert resp.status_code == 422


def test_login_with_correct_credentials_succeeds():
    client.post("/auth/register", json={"email": "jordan@example.com", "password": VALID_PASSWORD})
    resp = client.post("/auth/login", json={"email": "jordan@example.com", "password": VALID_PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["email"] == "jordan@example.com"


def test_login_with_wrong_password_fails():
    client.post("/auth/register", json={"email": "jordan@example.com", "password": VALID_PASSWORD})
    resp = client.post("/auth/login", json={"email": "jordan@example.com", "password": "Wrong-Password1"})
    assert resp.status_code == 401


def test_login_with_unknown_email_fails_with_the_same_generic_message():
    # Never reveal whether an account exists -- same message either way.
    known = client.post("/auth/login", json={"email": "jordan@example.com", "password": "whatever"})
    client.post("/auth/register", json={"email": "jordan@example.com", "password": VALID_PASSWORD})
    unknown = client.post("/auth/login", json={"email": "someone-else@example.com", "password": "whatever"})
    assert known.status_code == unknown.status_code == 401
    assert known.json()["detail"] == unknown.json()["detail"] == "Incorrect email or password."


def test_login_on_a_google_only_account_gets_a_distinct_honest_message():
    db = SessionLocal()
    db.add(models.User(email="google-user@example.com", google_sub="some-google-sub"))
    db.commit()
    db.close()

    resp = client.post("/auth/login", json={"email": "google-user@example.com", "password": "whatever"})
    assert resp.status_code == 401
    assert "different sign-in method" in resp.json()["detail"]


def test_login_is_rate_limited_after_repeated_attempts():
    client.post("/auth/register", json={"email": "jordan@example.com", "password": VALID_PASSWORD})
    responses = [
        client.post("/auth/login", json={"email": "jordan@example.com", "password": "wrong"})
        for _ in range(6)
    ]
    assert any(r.status_code == 429 for r in responses)
