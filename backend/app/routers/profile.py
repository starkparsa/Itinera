import json
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/profile", tags=["profile"])

# The only two fields stored as JSON-encoded Text (see models.UserProfile's
# docstring) -- listed once so the encode/decode direction is never
# duplicated below.
JSON_LIST_FIELDS = ("interests", "bucket_list_countries")


def _get_or_create_profile(db: Session, user: models.User) -> models.UserProfile:
    profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user.id).first()
    if profile is None:
        profile = models.UserProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _to_out(profile: models.UserProfile, user: models.User) -> schemas.ProfileOut:
    # display_name lives on User, not UserProfile -- everything else in
    # ProfileOut matches a UserProfile column name 1:1 by design.
    fields = {
        name: getattr(profile, name) for name in schemas.ProfileOut.model_fields if name != "display_name"
    }
    for field in JSON_LIST_FIELDS:
        fields[field] = json.loads(fields[field]) if fields[field] else []
    return schemas.ProfileOut(display_name=user.display_name, **fields)


@router.get("", response_model=schemas.ProfileOut)
def get_profile(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _to_out(_get_or_create_profile(db, user), user)


@router.put("", response_model=schemas.ProfileOut)
def update_profile(
    body: schemas.ProfileUpdate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, user)
    data = body.model_dump(exclude_unset=True)

    if "display_name" in data:
        display_name = data.pop("display_name")
        if display_name:
            user.display_name = display_name

    for field in JSON_LIST_FIELDS:
        if field in data and data[field] is not None:
            data[field] = json.dumps(data[field])
    for field, value in data.items():
        setattr(profile, field, value)

    # Set once, on the first real save -- never overwritten by a later edit,
    # so it keeps meaning "onboarding was actually completed" rather than
    # "most recently saved".
    if profile.onboarding_completed_at is None:
        profile.onboarding_completed_at = datetime.utcnow()

    db.commit()
    db.refresh(profile)
    return _to_out(profile, user)


@router.post("/onboarding/skip", response_model=schemas.ProfileOut)
def skip_onboarding(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = _get_or_create_profile(db, user)
    if profile.onboarding_skipped_at is None:
        profile.onboarding_skipped_at = datetime.utcnow()
        db.commit()
        db.refresh(profile)
    return _to_out(profile, user)
