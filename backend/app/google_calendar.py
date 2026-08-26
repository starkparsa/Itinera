"""Google Calendar push (build-order item 5, Phase D -- see CLAUDE.md
decision log, "Auth" row). Goes through `googleapiclient` directly, not
Gemini/MCP: the go/no-go check run before writing this found `google-genai`'s
MCP support still explicitly "experimental" and the Calendar MCP server
itself gated behind Google's Developer Preview Program -- neither is a base
to build on. This also fits the architecture better on its own merits:
pushing an itinerary to a calendar is a deterministic user click, never a
judgment call for Gemini to make (same reasoning that kept weather out of
the LLM tool-calling loop, see weather_service.py's module docstring).

Client vs. tool split (principle #3): this module is the client layer
(token storage/refresh, the raw Calendar API v3 call). The "tool" shaping
(what gets returned to the router) stays thin here since there's no LLM
prompt consuming this output -- it's rendered straight to the UI.
"""
import os
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from . import calendar_export, models, weather_service

TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class CalendarNotConnectedError(Exception):
    """Raised when a user has no stored Calendar credential yet -- the
    caller (routers/trips.py) turns this into a specific error response the
    frontend uses to prompt reconnection, distinct from a real failure."""


def _fernet() -> Fernet:
    if not TOKEN_ENCRYPTION_KEY:
        # Fails loudly, never silently stores plaintext -- same discipline
        # as auth.py's AUTH_BACKEND_SECRET check.
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
    return Fernet(TOKEN_ENCRYPTION_KEY.encode())


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def save_credentials(
    db: Session,
    user: models.User,
    access_token: str,
    refresh_token: str | None,
    expires_at: int,
) -> None:
    """Upserts the user's Calendar credential. `expires_at` is a Unix
    timestamp (seconds), matching Auth.js's `account.expires_at` shape.
    `refresh_token` is only ever sent by Google on first consent unless
    prompt=consent forces reissue (Auth.js is configured to do that here,
    see frontend/src/auth.ts) -- if this call ever does receive `None`, an
    existing stored refresh token is left untouched rather than clobbered.
    """
    credential = db.query(models.GoogleCalendarCredential).filter(
        models.GoogleCalendarCredential.user_id == user.id,
    ).first()

    encrypted_access = encrypt_token(access_token)
    expires_dt = datetime.utcfromtimestamp(expires_at)

    if credential is None:
        if not refresh_token:
            raise ValueError("First-time Calendar connection did not include a refresh_token")
        credential = models.GoogleCalendarCredential(
            user_id=user.id,
            encrypted_access_token=encrypted_access,
            encrypted_refresh_token=encrypt_token(refresh_token),
            access_token_expires_at=expires_dt,
        )
        db.add(credential)
    else:
        credential.encrypted_access_token = encrypted_access
        credential.access_token_expires_at = expires_dt
        if refresh_token:
            credential.encrypted_refresh_token = encrypt_token(refresh_token)

    db.commit()


def _load_credentials(db: Session, user: models.User) -> Credentials:
    """Builds a real google-auth Credentials object from the stored,
    decrypted tokens, refreshing first if the access token has expired --
    the refreshed token is persisted back so the next call doesn't need to
    refresh again. Raises CalendarNotConnectedError if the user never
    granted Calendar access at all."""
    row = db.query(models.GoogleCalendarCredential).filter(
        models.GoogleCalendarCredential.user_id == user.id,
    ).first()
    if row is None:
        raise CalendarNotConnectedError(f"User {user.id} has not connected Google Calendar")

    client_id = os.getenv("AUTH_GOOGLE_ID", "")
    client_secret = os.getenv("AUTH_GOOGLE_SECRET", "")

    creds = Credentials(
        token=decrypt_token(row.encrypted_access_token),
        refresh_token=decrypt_token(row.encrypted_refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[CALENDAR_SCOPE],
    )

    # 60s buffer so a token that's about to expire mid-request gets
    # refreshed now instead of failing partway through the API call.
    if row.access_token_expires_at <= datetime.utcnow() + timedelta(seconds=60):
        creds.refresh(GoogleAuthRequest())
        row.encrypted_access_token = encrypt_token(creds.token)
        row.access_token_expires_at = creds.expiry or (datetime.utcnow() + timedelta(hours=1))
        db.commit()

    return creds


def push_trip_to_calendar(db: Session, user: models.User, trip: "models.Trip") -> dict:
    """Pushes every itinerary item as a real Google Calendar event on the
    user's primary calendar. Reuses calendar_export.resolve_event_time --
    the exact same time-of-day resolution rule as the .ics export, so the
    two paths never disagree about what time an event lands at.

    Returns {"events_created": int}. Raises CalendarNotConnectedError if
    the user hasn't granted Calendar access, or googleapiclient.errors.HttpError
    on a real API failure (the caller maps both to clear HTTP responses).
    """
    if not trip.start_date:
        raise ValueError("Trip has no resolved start date; cannot push to calendar")

    creds = _load_credentials(db, user)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    # Unlike an .ics file (RFC 5545 allows a floating, timezone-less
    # DTSTART -- see calendar_export.py's deliberate design), Google
    # Calendar's REST API rejects a timed event with no timezone at all --
    # confirmed live ("Missing time zone definition for start time"). Same
    # free geocoding lookup weather_service already uses elsewhere in this
    # app gives us a real IANA zone for the destination at no extra API
    # cost; UTC is a last-resort fallback only when geocoding itself fails,
    # not a fabricated specific zone.
    timezone_name = weather_service.geocode_timezone(trip.destination) or "UTC"

    created = 0
    for item in trip.items:
        day_date = trip.start_date + timedelta(days=item.day_number - 1)
        start_time = calendar_export.resolve_event_time(item.time_of_day)

        event_body: dict = {
            "summary": item.activity,
            "location": trip.destination,
        }
        if item.notes:
            event_body["description"] = item.notes

        if start_time is not None:
            hour, minute = start_time
            start_dt = datetime.combine(day_date, datetime.min.time().replace(hour=hour, minute=minute))
            end_dt = start_dt + calendar_export.DEFAULT_EVENT_DURATION
            event_body["start"] = {"dateTime": start_dt.isoformat(), "timeZone": timezone_name}
            event_body["end"] = {"dateTime": end_dt.isoformat(), "timeZone": timezone_name}
        else:
            # All-day ("date") events have no time component -- timeZone is
            # inapplicable to them and Google's API doesn't expect one.
            event_body["start"] = {"date": day_date.isoformat()}
            event_body["end"] = {"date": (day_date + timedelta(days=1)).isoformat()}

        service.events().insert(calendarId="primary", body=event_body).execute()
        created += 1

    return {"events_created": created}


__all__ = [
    "CalendarNotConnectedError",
    "HttpError",
    "InvalidToken",
    "decrypt_token",
    "encrypt_token",
    "push_trip_to_calendar",
    "save_credentials",
]
