from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import google_calendar, models, password_auth, schemas
from ..auth import get_current_user
from ..database import get_db
from ..rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


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
    return schemas.UserAuthOut(id=user.id, email=user.email)


@router.post("/login", response_model=schemas.UserAuthOut)
@limiter.limit("5/minute")
def login(request: Request, body: schemas.LoginRequest, db: Session = Depends(get_db)):
    """Verifies email/password credentials for Auth.js's Credentials
    provider `authorize()` callback (frontend/src/auth.ts) -- same
    "FastAPI creates/verifies, Auth.js owns the session" split as
    /register. Rate-limited tighter than this app's 100/minute default
    (rate_limit.py) specifically to slow down credential-stuffing against
    real accounts, the one risk unique to a password-based method Google/
    Facebook sign-in don't have.

    One deliberately-generic error message for both "no such account" and
    "wrong password" (never reveals which), and a distinct, honest message
    for "this account has no password" (a Google-only account) rather than
    lumping it in with a wrong-password guess.
    """
    user = db.query(models.User).filter(models.User.email == body.email.lower()).first()
    if user is None or user.password_hash is None:
        if user is not None and user.password_hash is None:
            raise HTTPException(
                status_code=401,
                detail="This email is linked to a different sign-in method. Try Google instead.",
            )
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    if not password_auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

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
