import os

# Must run before app.database is imported anywhere -- swaps the DB target
# to an in-memory SQLite so tests don't need a live MySQL instance (CI runs
# this without spinning up a database container).
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.database import get_db
from app.main import app

TEST_GOOGLE_SUB = "test-google-sub"


def _test_current_user(db: Session = Depends(get_db)) -> models.User:
    """Stands in for auth.get_current_user in every test -- skips JWT
    verification entirely and returns a fixed test user, creating it on
    first use. Deliberately looked up/created lazily (at request time, via
    FastAPI's own dependency injection) rather than pre-seeded by a fixture,
    since each test's setup_function() drops and recreates all tables
    *before* the test body runs `client.post(...)` -- pre-seeding here
    would just get wiped."""
    user = db.query(models.User).filter(models.User.google_sub == TEST_GOOGLE_SUB).first()
    if user is None:
        user = models.User(google_sub=TEST_GOOGLE_SUB, email="test-user@example.com")
        db.add(user)
        db.flush()
    return user


@pytest.fixture(autouse=True)
def override_auth():
    # Every existing test predates real auth and calls client.post(...) with
    # no Authorization header at all -- without this override, they'd all
    # start failing with 401 the moment get_current_user became a required
    # dependency (see routers/trips.py::generate_trip, Phase B).
    app.dependency_overrides[get_current_user] = _test_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
