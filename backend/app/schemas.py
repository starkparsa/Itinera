from datetime import datetime

from pydantic import BaseModel


class TripRequest(BaseModel):
    prompt: str
    user_id: int = 1  # placeholder until auth is added
    days: int | None = None  # explicit trip length; if omitted, the LLM infers it from the prompt
    conversation_id: int | None = None  # continue an existing chat; omit to start a new one


class ItineraryItemOut(BaseModel):
    day_number: int
    time_of_day: str | None = None
    activity: str
    notes: str | None = None

    class Config:
        from_attributes = True


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
