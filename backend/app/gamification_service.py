"""Passport stamps + tiered badges, computed/awarded on demand when
GET /gamification/passport is called -- not hooked into trip generation
itself, so this stays a single, idempotent evaluation point rather than
two places that both need to agree on when an achievement "really"
qualifies. Safe to call on every request: xp_points is recomputed
(never incremented) from real trip stats each time, and new
UserAchievement rows are only inserted for codes that don't already
have one (the DB unique constraint is the actual idempotency guarantee,
same posture as this codebase's other "set once" patterns).
"""
from datetime import datetime

from sqlalchemy.orm import Session

from . import models, stats_service

XP_PER_TRIP = 10

# Static lookup, not a DB column (see models.UserAchievement's docstring) --
# tier/label/description can be rebalanced without a migration. Carried
# over from the confirmed gamification design (docs/design-references.md).
ACHIEVEMENT_DEFINITIONS: dict[str, dict] = {
    "first_trip": {
        "tier": "Common", "label": "First Trip",
        "description": "Planned your first itinerary.",
    },
    "three_trips": {
        "tier": "Common", "label": "Getting the Hang of It",
        "description": "Planned 3 trips.",
    },
    "ten_trips": {
        "tier": "Rare", "label": "Seasoned Planner",
        "description": "Planned 10 trips.",
    },
    "first_international": {
        "tier": "Rare", "label": "Passport Stamped",
        "description": "Planned a trip outside your home country.",
    },
    "five_countries": {
        "tier": "Epic", "label": "Globetrotter",
        "description": "Visited 5 different countries.",
    },
    "ten_countries": {
        "tier": "Legendary", "label": "World Wanderer",
        "description": "Visited 10 different countries.",
    },
}


def level_for_xp(xp_points: int) -> int:
    """Always computed, never stored -- see models.UserStats's docstring."""
    return 1 + xp_points // 100


def _qualifying_codes(stats: dict, home_country: str | None) -> set[str]:
    """Which achievement codes this user's current stats qualify for --
    pure function of stats_service.compute_trip_stats' output, no DB
    access, so it's trivially testable and impossible to accidentally
    query stale data from."""
    codes = set()
    if stats["trip_count"] >= 1:
        codes.add("first_trip")
    if stats["trip_count"] >= 3:
        codes.add("three_trips")
    if stats["trip_count"] >= 10:
        codes.add("ten_trips")
    if stats["country_count"] >= 5:
        codes.add("five_countries")
    if stats["country_count"] >= 10:
        codes.add("ten_countries")
    # Only fires when a home country is actually on file -- can't tell
    # "international" from "domestic" without one, and guessing would
    # violate CLAUDE.md principle #7 (don't invent data you weren't given).
    if home_country and any(c != home_country for c in stats["countries_visited"]):
        codes.add("first_international")
    return codes


def evaluate_and_award(user: models.User, db: Session) -> dict:
    """Recomputes this user's real trip stats, updates UserStats.xp_points
    to match (a set, not an increment -- see module docstring), and
    inserts a UserAchievement row for any newly-qualifying code that
    doesn't already have one. Returns {"newly_unlocked": [codes awarded
    in THIS call only]} -- callers combine this with the full achievement
    list for display. Caller does not need to commit; this commits its
    own writes (mirrors profile.py's _get_or_create_profile pattern)."""
    stats = stats_service.compute_trip_stats(user.id, db)

    user_stats = db.query(models.UserStats).filter(models.UserStats.user_id == user.id).first()
    if user_stats is None:
        user_stats = models.UserStats(user_id=user.id)
        db.add(user_stats)
    user_stats.xp_points = stats["trip_count"] * XP_PER_TRIP

    profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user.id).first()
    home_country = profile.country_region if profile else None

    already_earned = {
        row.code for row in db.query(models.UserAchievement).filter(models.UserAchievement.user_id == user.id)
    }
    newly_unlocked = sorted(_qualifying_codes(stats, home_country) - already_earned)

    for code in newly_unlocked:
        db.add(models.UserAchievement(user_id=user.id, code=code, earned_at=datetime.utcnow()))

    db.commit()
    return {"newly_unlocked": newly_unlocked}
