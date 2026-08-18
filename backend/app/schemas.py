from pydantic import BaseModel


class TripRequest(BaseModel):
    prompt: str
    user_id: int = 1  # placeholder until auth is added
    days: int | None = None  # explicit trip length; if omitted, the LLM infers it from the prompt


class ItineraryItemOut(BaseModel):
    day_number: int
    time_of_day: str | None = None
    activity: str
    notes: str | None = None

    class Config:
        from_attributes = True


class TripResponse(BaseModel):
    trip_id: int
    destination: str
    itinerary: list[ItineraryItemOut]
    note: str | None = None
