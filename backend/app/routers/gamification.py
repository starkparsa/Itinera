from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from .. import gamification_service, models, passport_service, schemas, stats_service
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/gamification", tags=["gamification"])


@router.get("/passport", response_model=schemas.PassportOut)
def get_passport(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # evaluate_and_award is safe to call on every request -- see its own
    # docstring for why this is the single evaluation point rather than a
    # separate hook in trips.py.
    result = gamification_service.evaluate_and_award(user, db)

    stats = stats_service.compute_trip_stats(user.id, db)
    user_stats = db.query(models.UserStats).filter(models.UserStats.user_id == user.id).first()
    xp_points = user_stats.xp_points if user_stats else 0

    real_trips = (
        db.query(models.Trip)
        .options(selectinload(models.Trip.items))
        .filter(models.Trip.user_id == user.id, models.Trip.is_edit.is_(False))
        .order_by(models.Trip.created_at)
        .all()
    )
    # Same destination + same real start_date -- the same trip
    # replanned/regenerated (or a test/demo artifact), collapsed to one
    # stamp. A dateless trip is never collapsed with anything, including
    # another dateless trip to the same city -- see
    # passport_service.deduplicate_stamps' own docstring for why.
    deduped_trips = passport_service.deduplicate_stamps(real_trips)
    stamps = [
        schemas.PassportStampOut(
            trip_id=t.id,
            destination=t.destination,
            accent=passport_service.accent_for_destination(t.destination),
            created_at=t.created_at,
            in_progress=not passport_service.is_trip_completed(
                t.start_date, max((i.day_number for i in t.items), default=0),
            ),
        )
        for t in deduped_trips
    ]

    achievements = (
        db.query(models.UserAchievement)
        .filter(models.UserAchievement.user_id == user.id)
        .order_by(models.UserAchievement.earned_at)
        .all()
    )
    achievements_out = [
        schemas.AchievementOut(
            code=a.code,
            label=gamification_service.ACHIEVEMENT_DEFINITIONS[a.code]["label"],
            description=gamification_service.ACHIEVEMENT_DEFINITIONS[a.code]["description"],
            tier=gamification_service.ACHIEVEMENT_DEFINITIONS[a.code]["tier"],
            earned_at=a.earned_at,
        )
        for a in achievements
        # Defensive, not expected in practice: skips silently rather than
        # 500ing if a stored code ever outlives its definition (e.g. after
        # a rename) instead of crashing the whole passport page over it.
        if a.code in gamification_service.ACHIEVEMENT_DEFINITIONS
    ]

    return schemas.PassportOut(
        level=gamification_service.level_for_xp(xp_points),
        xp_points=xp_points,
        trip_count=stats["trip_count"],
        distinct_destinations=stats["distinct_destinations"],
        countries_visited=stats["countries_visited"],
        stamps=stamps,
        achievements=achievements_out,
        newly_unlocked=result["newly_unlocked"],
    )
