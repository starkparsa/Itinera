from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    # Google's stable subject identifier (the OIDC "sub" claim) -- the real
    # join key for auth (see backend/app/auth.py), not email, which isn't
    # guaranteed stable across a Google account's lifetime. Nullable because
    # pre-auth placeholder users (see CLAUDE.md decision log, "Auth" row)
    # have none.
    google_sub = Column(String(255), unique=True, index=True, nullable=True)
    display_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    trips = relationship("Trip", back_populates="owner", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="owner", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False, default="New chat")
    # Cached findings from the agent tool-calling step, set once per
    # conversation. That step is currently paused (see agent_service.py) --
    # this stays "" until it's re-enabled -- but the column is left generic
    # since it was weather+currency before and may be more than currency
    # again later.
    agent_context = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="conversations")
    messages = relationship(
        "Message", back_populates="conversation",
        cascade="all, delete-orphan", order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
    trip = relationship("Trip")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # ondelete="SET NULL": deleting a conversation shouldn't be blocked by (or
    # cascade-delete) trips it produced -- MySQL enforces FK constraints by
    # default (unlike SQLite, which is why this only surfaced against a real
    # database), so without this, deleting any conversation that has
    # generated a trip raises an IntegrityError. The trip and its itinerary
    # survive; it just becomes unlinked from the (now-gone) chat thread.
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    destination = Column(String(255), nullable=False)
    prompt = Column(Text)  # the original natural-language request
    # Real calendar start date, resolved deterministically (date_resolver.py,
    # never LLM arithmetic -- CLAUDE.md principle #6) from the prompt. Null
    # when nothing date-like was said; the weather feature below just stays
    # inactive for that trip rather than guessing.
    start_date = Column(Date, nullable=True)
    # Cached per-day forecast (weather_service.py) as a small JSON blob, plus
    # when it was fetched -- avoids re-hitting Open-Meteo on every view/
    # follow-up (principles #4/#5). Refreshed only once stale; see
    # routers/trips.py's _fetch_weather_for_trip.
    weather_json = Column(Text, nullable=True)
    weather_fetched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="trips")
    items = relationship("ItineraryItem", back_populates="trip", cascade="all, delete-orphan")


class ItineraryItem(Base):
    __tablename__ = "itinerary_items"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False)
    day_number = Column(Integer, nullable=False)
    time_of_day = Column(String(50))  # e.g. "morning", "14:00"
    activity = Column(Text, nullable=False)
    notes = Column(Text)

    trip = relationship("Trip", back_populates="items")


class GoogleCalendarCredential(Base):
    """One row per user who has granted the Calendar OAuth scope (Phase D,
    see CLAUDE.md decision log, "Auth" row) -- separate from login, which
    only ever needs the base openid/email/profile scopes. Tokens are
    encrypted at rest (google_calendar.py, via `cryptography.fernet` and
    TOKEN_ENCRYPTION_KEY) -- a plaintext refresh token in the DB would be a
    real credential leak if the DB were ever compromised.
    """
    __tablename__ = "google_calendar_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    encrypted_access_token = Column(Text, nullable=False)
    # Google only issues a refresh token on the *first* consent unless the
    # OAuth request forces prompt=consent every time (which Auth.js is
    # configured to do here specifically so this is never left null after a
    # real grant -- see frontend/src/auth.ts).
    encrypted_refresh_token = Column(Text, nullable=False)
    access_token_expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User")
