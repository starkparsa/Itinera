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
(Google, email/password via a Credentials provider, and now Facebook).
`sub`'s *meaning* depends on `provider`: for "google"/"facebook" it's
that provider's own stable subject id, matched against User.google_sub/
User.facebook_id respectively; for "credentials" it's this app's own
internal User.id (already known -- routers/auth.py's /auth/login just
confirmed the account exists), matched directly and never
auto-provisioned, since an email/password account can only ever be
created through /auth/register.

Extended again the same day to guard OAuth auto-provisioning against an
email collision: a brand-new Google or Facebook identity whose email
already belongs to a *different* existing account (e.g. one created via
/auth/register, or via the other OAuth provider) is rejected with a
clean 401 instead of silently linking onto that row or crashing on the
users.email unique constraint. Deliberately NOT auto-linked -- this
app's email/password signup has no email-verification step, so an
attacker could pre-register a victim's email with a password they
control; silently linking a later real OAuth login onto that same row
would hand the attacker access to it. The same gap existed for Google
alone before this, just unreachable until email/password added a second
way to claim an email.
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

    if provider == "facebook":
        id_column = models.User.facebook_id
        placeholder_domain = "users.noreply.facebook.com"
    else:
        # "google" -- the original Phase-C behavior, and the default for
        # any token predating the provider claim.
        id_column = models.User.google_sub
        placeholder_domain = "users.noreply.google.com"

    user = db.query(models.User).filter(id_column == sub).first()
    if user is None:
        # Auto-provisioning a *new* identity: refuse to silently attach to
        # (or crash on) an existing account under a different sign-in
        # method that happens to share this email -- see the module
        # docstring above.
        if email:
            existing = db.query(models.User).filter(models.User.email == email).first()
            if existing is not None:
                raise HTTPException(
                    status_code=401,
                    detail="This email is linked to a different sign-in method.",
                )
        user = models.User(email=email or f"{sub}@{placeholder_domain}")
        setattr(user, id_column.key, sub)
        db.add(user)
        db.flush()  # visible to the rest of this request before the route's own commit

    return user
