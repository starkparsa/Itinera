from app import models, stats_service
from app.database import Base, SessionLocal, engine


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _make_user(db, email="stats-test@example.com"):
    user = models.User(email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_trip(db, user, destination, is_edit=False):
    trip = models.Trip(user_id=user.id, destination=destination, is_edit=is_edit)
    db.add(trip)
    db.commit()
    return trip


def test_zero_trip_user_returns_zeros_and_empty():
    db = SessionLocal()
    user = _make_user(db)

    stats = stats_service.compute_trip_stats(user.id, db)

    assert stats == {
        "trip_count": 0,
        "distinct_destinations": 0,
        "countries_visited": [],
        "country_count": 0,
    }
    db.close()


def test_counts_trips_and_dedupes_distinct_destinations():
    db = SessionLocal()
    user = _make_user(db)
    _make_trip(db, user, "Paris")
    _make_trip(db, user, "Paris")  # same destination, still a separate real trip
    _make_trip(db, user, "Tokyo")

    stats = stats_service.compute_trip_stats(user.id, db)

    assert stats["trip_count"] == 3
    assert stats["distinct_destinations"] == 2
    db.close()


def test_excludes_edit_regenerated_trips_from_every_count():
    db = SessionLocal()
    user = _make_user(db)
    _make_trip(db, user, "Paris", is_edit=False)
    _make_trip(db, user, "Paris", is_edit=True)  # a conversational tweak, not a new trip
    _make_trip(db, user, "Paris", is_edit=True)

    stats = stats_service.compute_trip_stats(user.id, db)

    assert stats["trip_count"] == 1
    assert stats["distinct_destinations"] == 1
    db.close()


def test_infer_country_matches_known_substrings_case_insensitively():
    assert stats_service.infer_country("a week in tokyo") == "Japan"
    assert stats_service.infer_country("TOKYO") == "Japan"
    assert stats_service.infer_country("Lisbon getaway") == "Portugal"


def test_infer_country_never_guesses_an_unrecognized_destination():
    assert stats_service.infer_country("a small town nobody's heard of") is None
    assert stats_service.infer_country("") is None


def test_countries_visited_deduped_and_sorted():
    db = SessionLocal()
    user = _make_user(db)
    _make_trip(db, user, "Paris")
    _make_trip(db, user, "Lyon")  # also France -- should not double-count the country
    _make_trip(db, user, "Tokyo")
    _make_trip(db, user, "a town nobody's heard of")  # unrecognized -- excluded, not guessed

    stats = stats_service.compute_trip_stats(user.id, db)

    assert stats["countries_visited"] == ["France", "Japan"]
    assert stats["country_count"] == 2
    db.close()
