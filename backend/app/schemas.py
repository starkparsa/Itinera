from datetime import date, datetime

from pydantic import BaseModel


class TripRequest(BaseModel):
    prompt: str
    days: int | None = None  # explicit trip length; if omitted, the LLM infers it from the prompt
    conversation_id: int | None = None  # continue an existing chat; omit to start a new one
    # No user_id field -- as of Phase C (see CLAUDE.md decision log, "Auth"
    # row), the user is always derived from a verified JWT
    # (auth.get_current_user), never from a client-supplied field. A field
    # here would just be a second, untrustworthy source of truth for
    # something auth already provides correctly.


class ItineraryItemOut(BaseModel):
    day_number: int
    time_of_day: str | None = None
    activity: str
    notes: str | None = None

    class Config:
        from_attributes = True


class DayWeatherOut(BaseModel):
    day_number: int
    date: date
    temp_min: float
    temp_max: float
    temp_min_f: float
    temp_max_f: float
    condition: str


class TripResponse(BaseModel):
    trip_id: int | None = None
    destination: str | None = None
    itinerary: list[ItineraryItemOut] = []
    note: str | None = None
    agent_context: str | None = None
    # Nullable: a trip's conversation can be deleted out from under it
    # (Trip.conversation_id is ON DELETE SET NULL, see models.py) and old
    # trips predating conversation linkage never had one either.
    conversation_id: int | None = None
    reply: str | None = None  # plain-text reply for question/off-topic turns (no itinerary generated)
    # Real forecast per day, only for days within Open-Meteo's horizon and
    # only when a start date was resolvable -- empty, never fabricated, is
    # the fallback (see date_resolver.py / weather_service.py).
    weather: list[DayWeatherOut] = []
    # Resolved trip start date, or None if the prompt never named one (see
    # date_resolver.py). The frontend uses this, not a guess, to decide
    # whether to show a calendar-export button at all -- see
    # calendar_export.py.
    start_date: date | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    trip: TripResponse | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationSummary(BaseModel):
    id: int
    title: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    id: int
    title: str
    created_at: datetime
    messages: list[MessageOut]
    # Conversation-level state (see models.Conversation.tour_guide_mode) --
    # exposed here, not on TripResponse, since a question-turn's assistant
    # Message has no trip attached at all; this is the frontend's only way
    # to know whether to show tour-guide-mode styling (see CLAUDE.md).
    tour_guide_mode: bool
