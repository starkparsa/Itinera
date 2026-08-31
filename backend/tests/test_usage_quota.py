from datetime import date, timedelta
from unittest.mock import patch

from app import models, usage_quota
from app.database import Base, SessionLocal, engine


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _make_user(google_sub="quota-user") -> models.User:
    db = SessionLocal()
    try:
        user = models.User(google_sub=google_sub, email=f"{google_sub}@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def test_first_request_of_the_day_consumes_one_unit():
    db = SessionLocal()
    try:
        user = _make_user()
        assert usage_quota.check_and_consume_daily_quota(user, db) is True
        assert user.daily_request_count == 1
        assert user.daily_request_count_date == date.today()
    finally:
        db.close()


def test_requests_up_to_the_limit_all_succeed():
    db = SessionLocal()
    try:
        user = _make_user()
        with patch("app.usage_quota.DAILY_TRIP_GENERATION_LIMIT", 3):
            results = [usage_quota.check_and_consume_daily_quota(user, db) for _ in range(3)]
        assert results == [True, True, True]
        assert user.daily_request_count == 3
    finally:
        db.close()


def test_request_beyond_the_limit_is_rejected_without_incrementing_further():
    db = SessionLocal()
    try:
        user = _make_user()
        with patch("app.usage_quota.DAILY_TRIP_GENERATION_LIMIT", 2):
            usage_quota.check_and_consume_daily_quota(user, db)
            usage_quota.check_and_consume_daily_quota(user, db)
            third = usage_quota.check_and_consume_daily_quota(user, db)

        assert third is False
        assert user.daily_request_count == 2  # not bumped to 3 by the rejected call
    finally:
        db.close()


def test_counter_resets_on_a_new_calendar_day():
    db = SessionLocal()
    try:
        user = _make_user()
        with patch("app.usage_quota.DAILY_TRIP_GENERATION_LIMIT", 1):
            usage_quota.check_and_consume_daily_quota(user, db)
            assert user.daily_request_count == 1

            # Simulate yesterday's count carrying over -- a request today
            # should reset rather than staying stuck at the limit.
            user.daily_request_count_date = date.today() - timedelta(days=1)
            db.commit()

            result = usage_quota.check_and_consume_daily_quota(user, db)

        assert result is True
        assert user.daily_request_count == 1
        assert user.daily_request_count_date == date.today()
    finally:
        db.close()


def test_two_different_users_have_independent_quotas():
    db = SessionLocal()
    try:
        user_a = _make_user("user-a")
        user_b = _make_user("user-b")

        with patch("app.usage_quota.DAILY_TRIP_GENERATION_LIMIT", 1):
            assert usage_quota.check_and_consume_daily_quota(user_a, db) is True
            assert usage_quota.check_and_consume_daily_quota(user_a, db) is False
            # user_b's quota is untouched by user_a's usage.
            assert usage_quota.check_and_consume_daily_quota(user_b, db) is True
    finally:
        db.close()
