from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app

client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_get_profile_creates_an_empty_row_on_first_call():
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pace"] is None
    assert body["interests"] == []
    assert body["onboarding_completed_at"] is None


def test_put_profile_persists_partial_update():
    resp = client.put("/profile", json={"pace": "balanced", "interests": ["food", "culture"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["pace"] == "balanced"
    assert body["interests"] == ["food", "culture"]
    assert body["onboarding_completed_at"] is not None

    # Persisted, not just echoed back
    assert client.get("/profile").json()["pace"] == "balanced"


def test_put_profile_does_not_overwrite_unset_fields():
    client.put("/profile", json={"pace": "balanced"})
    resp = client.put("/profile", json={"budget_tier": "mid"})
    body = resp.json()
    assert body["pace"] == "balanced"
    assert body["budget_tier"] == "mid"


def test_onboarding_completed_at_set_once_not_on_every_edit():
    first = client.put("/profile", json={"pace": "balanced"}).json()
    second = client.put("/profile", json={"pace": "packed"}).json()
    assert first["onboarding_completed_at"] == second["onboarding_completed_at"]


def test_skip_onboarding_sets_skipped_not_completed():
    body = client.post("/profile/onboarding/skip").json()
    assert body["onboarding_skipped_at"] is not None
    assert body["onboarding_completed_at"] is None


def test_skip_onboarding_is_idempotent():
    first = client.post("/profile/onboarding/skip").json()
    second = client.post("/profile/onboarding/skip").json()
    assert first["onboarding_skipped_at"] == second["onboarding_skipped_at"]


def test_put_profile_persists_account_details():
    resp = client.put(
        "/profile",
        json={"mobile_number": "+15550100", "date_of_birth": "1990-06-15", "country_region": "United States"},
    )
    body = resp.json()
    assert body["mobile_number"] == "+15550100"
    assert body["date_of_birth"] == "1990-06-15"
    assert body["country_region"] == "United States"


def test_put_profile_display_name_updates_the_user_row_not_the_profile_table():
    resp = client.put("/profile", json={"display_name": "Jordan Lee"})
    assert resp.json()["display_name"] == "Jordan Lee"
    # Reflected on a fresh GET too -- confirms it's actually persisted on
    # User, not just echoed back from the request body.
    assert client.get("/profile").json()["display_name"] == "Jordan Lee"


def test_put_profile_blank_display_name_does_not_clear_the_real_name():
    client.put("/profile", json={"display_name": "Jordan Lee"})
    client.put("/profile", json={"display_name": ""})
    assert client.get("/profile").json()["display_name"] == "Jordan Lee"


def test_put_profile_rejects_an_invalid_phone_number():
    resp = client.put("/profile", json={"mobile_number": "not a phone number"})
    assert resp.status_code == 422


def test_put_profile_rejects_a_future_date_of_birth():
    resp = client.put("/profile", json={"date_of_birth": "2999-01-01"})
    assert resp.status_code == 422


def test_put_profile_rejects_an_implausible_date_of_birth():
    resp = client.put("/profile", json={"date_of_birth": "1850-01-01"})
    assert resp.status_code == 422


def test_put_profile_accepts_a_plausible_phone_and_dob():
    resp = client.put("/profile", json={"mobile_number": "+1 (555) 010-0100", "date_of_birth": "1990-06-15"})
    assert resp.status_code == 200
