"""JWT verification for the Next.js <-> FastAPI bridge (the BFF pattern
decided for Google OAuth -- see CLAUDE.md's decision log, "Auth" row).

Next.js (Auth.js) is the OAuth client and session owner; it never shares
Auth.js's own session cookie with this backend. Instead, on every backend
call, Next.js mints a short-lived, backend-scoped JWT (see frontend/src/
lib/backend.ts) signed with a secret shared between the two services
(AUTH_BACKEND_SECRET) and sends it as `Authorization: Bearer <token>`. This
backend never talks to Google directly and never sees a real Google token
-- it only ever verifies this one JWT.

python-jose does the actual verification -- no hand-rolled crypto, per the
explicit decision not to build session/security logic in-house.

Extended 2026-09-07 (login page redesign) to also carry a `provider`
claim, since Auth.js now has more than one way to establish a session
(Google, and email/password via a Credentials provider -- Facebook is
next). `sub`'s *meaning* depends on `provider`: for "google" it's still
Google's OIDC subject, matched against User.google_sub exactly as before;
for "credentials" it's this app's own internal User.id (already known --
routers/auth.py's /auth/login just confirmed the account exists), matched
directly and never auto-provisioned, since an email/password account can
only ever be created through /auth/register.
"""
import os

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from . import models
from .database import get_db

AUTH_BACKEND_SECRET = os.getenv("AUTH_BACKEND_SECRET", "")
ALGORITHM = "HS256"


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    """FastAPI dependency: verifies the bearer JWT and returns the
    corresponding User. Raises 401 on anything not verifiable -- never
    falls back to a default user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    if not AUTH_BACKEND_SECRET:
        # A missing secret must fail loudly, never be treated as "auth is
        # off" -- silently accepting any token would defeat the whole point.
        raise HTTPException(status_code=500, detail="AUTH_BACKEND_SECRET is not configured")

    try:
        payload = jwt.decode(token, AUTH_BACKEND_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing subject claim")
    email = payload.get("email")
    # Absent claim defaults to "google" -- old tokens minted before this
    # claim existed, and any real client still built against that shape,
    # keep working unchanged.
    provider = payload.get("provider", "google")

    if provider == "credentials":
        try:
            user = db.query(models.User).filter(models.User.id == int(sub)).first()
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid subject claim")
        if user is None:
            raise HTTPException(status_code=401, detail="Account not found")
        return user

    # "google" (and, once wired, "facebook") -- auto-provision on first
    # sight of a new OAuth identity, the original Phase-C behavior.
    user = db.query(models.User).filter(models.User.google_sub == sub).first()
    if user is None:
        user = models.User(google_sub=sub, email=email or f"{sub}@users.noreply.google.com")
        db.add(user)
        db.flush()  # visible to the rest of this request before the route's own commit

    return user
