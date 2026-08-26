from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import google_calendar, models
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleCalendarTokenRequest(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_at: int  # Unix timestamp (seconds) -- matches Auth.js's account.expires_at


@router.post("/google-calendar-token")
def save_google_calendar_token(
    request: GoogleCalendarTokenRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Called server-side by the frontend's Auth.js `jwt` callback right
    after Google grants the Calendar scope (frontend/src/auth.ts) -- never
    reached by the browser directly, and the raw Google tokens never touch
    it either, only this backend-to-backend call. See google_calendar.py
    for why these are encrypted at rest."""
    try:
        google_calendar.save_credentials(
            db, user, request.access_token, request.refresh_token, request.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"saved": True}


@router.get("/google-calendar-status")
def google_calendar_status(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Lets the frontend decide whether to show "Push to Calendar" or
    "Connect Google Calendar" without guessing from a failed push."""
    connected = (
        db.query(models.GoogleCalendarCredential)
        .filter(models.GoogleCalendarCredential.user_id == user.id)
        .first()
        is not None
    )
    return {"connected": connected}
