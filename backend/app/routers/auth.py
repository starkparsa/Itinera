import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import google_calendar, models, password_auth, schemas
from ..auth import get_current_user
from ..database import get_db
from ..rate_limit import limiter
from . import conversations

router = APIRouter(prefix="/auth", tags=["auth"])
# Auth events only (signup, login success/failure) -- a security-monitoring
# trail distinct from this app's normal request logs. Never logs a password,
# hashed or not; logs the attempted email on failure (useful for spotting a
# single account under sustained attack) but not on success, where the new
# user_id already identifies the row uniquely.
logger = logging.getLogger(__name__)


@router.post("/register", response_model=schemas.UserAuthOut, status_code=201)
def register(request: schemas.RegisterRequest, db: Session = Depends(get_db)):
    """Creates an email/password account. Called from Auth.js's side
    (frontend/src/app/login/actions.ts) before signing the user in --
    FastAPI only ever creates the row here, it never mints a session
    itself (see UserAuthOut's docstring).

    Deliberately rejects ANY existing email, including a Google-only
    account with the same address, rather than silently attaching a
    password to it -- account linking across auth methods is a real
    security decision (does owning the inbox prove ownership of the
    existing account?) that hasn't been made yet, not something to
    improvise here. See decisions.md's Login page redesign entry.
    """
    existing = db.query(models.User).filter(models.User.email == request.email).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = models.User(email=request.email, password_hash=password_auth.hash_password(request.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Signup succeeded: user_id=%s", user.id)
    return schemas.UserAuthOut(id=user.id, email=user.email)


@router.post("/login", response_model=schemas.UserAuthOut)
@limiter.limit("5/minute")
def login(request: Request, body: schemas.LoginRequest, db: Session = Depends(get_db)):
    """Verifies email/password credentials for Auth.js's Credentials
    provider `authorize()` callback (frontend/src/auth.ts) -- same
    "FastAPI creates/verifies, Auth.js owns the session" split as
    /register. Rate-limited tighter than this app's 100/minute default
    (rate_limit.py) specifically to slow down credential-stuffing against
    real accounts, the one risk unique to a password-based method Google
    sign-in doesn't have.

    One deliberately-generic error message for both "no such account" and
    "wrong password" (never reveals which), and a distinct, honest message
    for "this account has no password" (a Google-only account) rather than
    lumping it in with a wrong-password guess.

    Every outcome (success, and each failure reason) is logged for security
    monitoring -- see the module-level `logger`. Never the password, hashed
    or not; the attempted email is logged only on failure (a success is
    already uniquely identified by the new user_id).
    """
    email = body.email.lower()
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None or user.password_hash is None:
        if user is not None and user.password_hash is None:
            logger.warning("Login failed (wrong sign-in method): email=%s ip=%s", email, request.client.host if request.client else "unknown")
            raise HTTPException(
                status_code=401,
                detail="This email is linked to a different sign-in method. Try Google instead.",
            )
        logger.warning("Login failed (no such account): email=%s ip=%s", email, request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    if not password_auth.verify_password(body.password, user.password_hash):
        logger.warning("Login failed (wrong password): user_id=%s ip=%s", user.id, request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    logger.info("Login succeeded: user_id=%s", user.id)
    return schemas.UserAuthOut(id=user.id, email=user.email)


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


@router.delete("/account")
def delete_account(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Permanently deletes the authenticated user's account and every row
    it owns -- explicit user request, 2026-09-09 ("the ability for the
    user to delete their data completely when they delete their
    profile"). Irreversible, no soft-delete, no grace period -- the
    frontend's own confirmation dialog is the only guard, same pattern
    conversations.delete_conversation already uses.

    Reuses conversations.purge_conversation for every conversation this
    user owns (gets the same messages-before-trips FK ordering right
    that function already had to solve), then removes the other tables a
    User can own 1:1/1:many (UserProfile, GoogleCalendarCredential,
    UserStats, UserAchievement -- none of these have further children
    needing their own cascade), then any trip left with no conversation
    at all (a legacy orphan, or one from a future path that doesn't go
    through routers/conversations.py), then the User row itself.

    Does NOT revoke the Google OAuth grant at Google's own end -- this
    deletes this app's copy of the data; a user who also wants Google's
    side revoked can do that separately at
    myaccount.google.com/permissions. A deliberate scope line, not an
    oversight -- see decisions.md.
    """
    for conversation in db.query(models.Conversation).filter(models.Conversation.user_id == user.id).all():
        conversations.purge_conversation(db, conversation)

    # Conversation-less trips (a legacy orphan predating the
    # conversation_id link, or any future path that skips
    # routers/conversations.py's own purge) -- the loop above only
    # touches trips tied to a conversation it's deleting.
    for trip in db.query(models.Trip).filter(models.Trip.user_id == user.id).all():
        db.delete(trip)

    db.query(models.UserProfile).filter(models.UserProfile.user_id == user.id).delete()
    db.query(models.GoogleCalendarCredential).filter(models.GoogleCalendarCredential.user_id == user.id).delete()
    db.query(models.UserStats).filter(models.UserStats.user_id == user.id).delete()
    db.query(models.UserAchievement).filter(models.UserAchievement.user_id == user.id).delete()

    user_id = user.id  # captured before delete -- the ORM instance expires after commit
    db.delete(user)
    db.commit()
    logger.info("Account deleted: user_id=%s", user_id)
    return {"deleted": True}
