from app import gamification_service, models
from app.database import Base, SessionLocal, engine


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _make_user(db, email="gamify-test@example.com"):
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


def test_first_trip_awarded_after_the_first_real_trip():
    db = SessionLocal()
    user = _make_user(db)
    _make_trip(db, user, "Paris")

    result = gamification_service.evaluate_and_award(user, db)

    assert result["newly_unlocked"] == ["first_trip"]
    db.close()


def test_first_trip_not_re_awarded_on_a_second_call():
    db = SessionLocal()
    user = _make_user(db)
    _make_trip(db, user, "Paris")

    gamification_service.evaluate_and_award(user, db)
    second = gamification_service.evaluate_and_award(user, db)

    assert second["newly_unlocked"] == []
    earned = db.query(models.UserAchievement).filter(
        models.UserAchievement.user_id == user.id, models.UserAchievement.code == "first_trip"
    ).all()
    assert len(earned) == 1  # the unique constraint (or app logic) never lets a second row in
    db.close()


def test_three_trips_and_ten_trips_thresholds():
    db = SessionLocal()
    user = _make_user(db)
    for i in range(3):
        _make_trip(db, user, f"City {i}")

    result = gamification_service.evaluate_and_award(user, db)
    assert "three_trips" in result["newly_unlocked"]
    assert "ten_trips" not in result["newly_unlocked"]

    for i in range(3, 10):
        _make_trip(db, user, f"City {i}")
    result = gamification_service.evaluate_and_award(user, db)
    assert result["newly_unlocked"] == ["ten_trips"]  # three_trips already earned, not re-listed
    db.close()


def test_edit_regenerated_trips_never_count_toward_thresholds():
    db = SessionLocal()
    user = _make_user(db)
    _make_trip(db, user, "Paris", is_edit=False)
    for _ in range(5):
        _make_trip(db, user, "Paris", is_edit=True)  # conversational tweaks, not new trips

    result = gamification_service.evaluate_and_award(user, db)

    assert result["newly_unlocked"] == ["first_trip"]  # not three_trips
    db.close()


def test_first_international_does_not_fire_without_a_home_country_on_file():
    db = SessionLocal()
    user = _make_user(db)
    _make_trip(db, user, "Tokyo")
    # No UserProfile row at all -- home_country is unknowable, must not guess.

    result = gamification_service.evaluate_and_award(user, db)

    assert "first_international" not in result["newly_unlocked"]
    db.close()


def test_first_international_fires_when_a_trip_country_differs_from_home():
    db = SessionLocal()
    user = _make_user(db)
    db.add(models.UserProfile(user_id=user.id, country_region="United States"))
    db.commit()
    _make_trip(db, user, "Tokyo")

    result = gamification_service.evaluate_and_award(user, db)

    assert "first_international" in result["newly_unlocked"]
    db.close()


def test_first_international_does_not_fire_for_a_domestic_trip():
    db = SessionLocal()
    user = _make_user(db)
    db.add(models.UserProfile(user_id=user.id, country_region="Japan"))
    db.commit()
    _make_trip(db, user, "Tokyo")  # infers to Japan -- matches home country

    result = gamification_service.evaluate_and_award(user, db)

    assert "first_international" not in result["newly_unlocked"]
    db.close()


def test_five_and_ten_countries_thresholds():
    db = SessionLocal()
    user = _make_user(db)
    for city in ["Paris", "Tokyo", "Bangkok", "Cairo", "Lima"]:
        _make_trip(db, user, city)

    result = gamification_service.evaluate_and_award(user, db)

    assert "five_countries" in result["newly_unlocked"]
    assert "ten_countries" not in result["newly_unlocked"]
    db.close()


def test_xp_points_set_from_real_trip_count_not_incremented():
    db = SessionLocal()
    user = _make_user(db)
    _make_trip(db, user, "Paris")

    gamification_service.evaluate_and_award(user, db)
    gamification_service.evaluate_and_award(user, db)  # called twice -- must not double the XP

    user_stats = db.query(models.UserStats).filter(models.UserStats.user_id == user.id).first()
    assert user_stats.xp_points == gamification_service.XP_PER_TRIP
    db.close()


def test_level_for_xp_is_a_pure_computed_formula():
    assert gamification_service.level_for_xp(0) == 1
    assert gamification_service.level_for_xp(99) == 1
    assert gamification_service.level_for_xp(100) == 2
    assert gamification_service.level_for_xp(250) == 3
