from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
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
    # Per-account daily quota on POST /trips/generate (see
    # app/usage_quota.py) -- distinct from rate_limit.py's IP-keyed slowapi
    # limiter, which is flood/abuse protection, not a real per-account cost
    # cap (a shared IP, or one account rotating IPs, isn't bounded by it the
    # way this is). daily_request_count_date is the calendar day this
    # count applies to; a request on a new day resets the counter rather
    # than accumulating forever. DB-backed (not in-memory, unlike
    # rate_limit.py's limiter) specifically so it stays correct if the
    # backend is ever horizontally scaled -- see usage_quota.py for the
    # full rationale.
    daily_request_count = Column(Integer, nullable=False, default=0)
    daily_request_count_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    trips = relationship("Trip", back_populates="owner", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="owner", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    # Indexed: filtered on for every ownership check across trips.py/
    # conversations.py (list_conversations, plus every 404-on-cross-user-id
    # check) -- a foreign key column gets no index automatically in
    # Postgres (unlike the primary key it references), so this was a real
    # full-table-scan-per-query gap. Fixed 2026-08-31 across every FK
    # column in this file, see the Alembic migration adding them.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False, default="New chat")
    # Cached findings from the agent tool-calling step, set once per
    # conversation. That step is currently paused (see agent_service.py) --
    # this stays "" until it's re-enabled -- but the column is left generic
    # since it was weather+currency before and may be more than currency
    # again later.
    agent_context = Column(Text, nullable=True)
    # True once the user has explicitly asked the assistant to act as a
    # tour guide (classify_intent's tour_guide_requested) -- stays True
    # across later question turns, even ones that don't repeat that
    # phrasing, until the next new_trip/edit_trip-classified turn flips it
    # back to False. See routers/trips.py's question and
    # new_trip/edit_trip branches.
    tour_guide_mode = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="conversations")
    messages = relationship(
        "Message", back_populates="conversation",
        cascade="all, delete-orphan", order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    # Indexed -- every conversation load (routers/conversations.py) filters
    # messages by this via the Conversation.messages relationship; see
    # Conversation.user_id's comment above for why this needs to be
    # explicit.
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
    trip = relationship("Trip")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    # Indexed -- see Conversation.user_id's comment above.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # ondelete="SET NULL": deleting a conversation shouldn't be blocked by (or
    # cascade-delete) trips it produced -- MySQL enforces FK constraints by
    # default (unlike SQLite, which is why this only surfaced against a real
    # database), so without this, deleting any conversation that has
    # generated a trip raises an IntegrityError. The trip and its itinerary
    # survive; it just becomes unlinked from the (now-gone) chat thread.
    # Indexed for the same reason as every other FK here -- looked up on
    # every question/edit turn (routers/trips.py's latest_trip/previous_trip
    # queries) and on every conversation reload.
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
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
    # Indexed -- see Conversation.user_id's comment above; loaded via
    # Trip.items on every trip/conversation read.
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False, index=True)
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
