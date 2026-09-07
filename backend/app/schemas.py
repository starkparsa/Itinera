import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Loose on purpose -- catches a name typed into the phone field or similar
# nonsense, not meant to validate real dialing-plan correctness (that's
# what actually sending an SMS would tell you, and this app doesn't send
# one yet).
_PHONE_RE = re.compile(r"^\+?[0-9\s().-]{7,20}$")
MAX_PLAUSIBLE_AGE = 120


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

    model_config = ConfigDict(from_attributes=True)


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
    # Auto-persisted places (see models.SavedPlace) -- empty until a
    # find_nearby_places/get_place_details tool call has actually
    # succeeded for this trip, never fabricated in between. Forward
    # reference ("SavedPlaceOut" defined below) -- resolved by Pydantic
    # once the whole module has loaded, same as any other in-module
    # forward ref.
    saved_places: list["SavedPlaceOut"] = []


class TripSummary(BaseModel):
    """One row for the 'Your Trips' list (GET /trips) -- deliberately
    smaller than TripResponse, which carries a full itinerary/weather
    payload meant for a single open trip, not a list of many. `status` is
    computed in Python (trip_status.derive_status), never guessed by the
    LLM -- see CLAUDE.md principle #6's date-arithmetic rule, which this
    extends to trip status the same way."""

    id: int
    destination: str
    start_date: date | None = None
    day_count: int  # max(item.day_number) over the trip's itinerary; 0 if somehow empty
    status: str  # "draft" | "upcoming" | "completed"
    created_at: datetime
    # Both null when PEXELS_API_KEY is unset or the search found nothing --
    # the frontend falls back to a flat color banner, never a broken image.
    photo_url: str | None = None
    photo_credit: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SavedPlaceOut(BaseModel):
    """A place find_nearby_places/get_place_details surfaced for a trip and
    that got auto-persisted (models.SavedPlace) -- see routers/trips.py's
    generate_trip/question-branch wiring."""

    name: str
    address: str | None = None
    rating: float | None = None
    price_level: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    trip: TripResponse | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationSummary(BaseModel):
    id: int
    title: str
    created_at: datetime
    # The latest Trip row generated in this conversation, if any -- lets the
    # frontend route straight to that trip's "/trips/[tripId]" Trip Hub page
    # instead of the plain chat view (routers/conversations.py's
    # list_conversations computes this the same way routers/trips.py's
    # list_trips already does: latest Trip per conversation_id). None for a
    # conversation that hasn't generated an itinerary yet -- it has no Trip
    # Hub page to go to.
    trip_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ProfileUpdate(BaseModel):
    """Partial update -- every field optional, since the onboarding form is
    fully skippable and Profile -> Edit preferences reuses this same shape
    for a single-field change.

    display_name isn't a UserProfile column -- it's User.display_name
    (Google-sourced), included here so the "what should we call you"
    account-details question can go through the same single PUT rather
    than a second endpoint. The router writes it to the User row, not
    UserProfile.
    """

    display_name: str | None = None
    mobile_number: str | None = Field(default=None, max_length=30)
    date_of_birth: date | None = None
    country_region: str | None = Field(default=None, max_length=100)
    travel_frequency: str | None = None
    pace: str | None = None
    budget_tier: str | None = None
    interests: list[str] | None = None
    travel_companions: str | None = None
    typical_trip_length_days: int | None = None
    dietary_needs: str | None = None
    accessibility_needs: str | None = None
    bucket_list_countries: list[str] | None = None
    additional_preferences: str | None = None

    @field_validator("mobile_number")
    @classmethod
    def _validate_mobile_number(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not _PHONE_RE.match(value):
            raise ValueError("Doesn't look like a valid phone number")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def _validate_date_of_birth(cls, value: date | None) -> date | None:
        if value is None:
            return value
        today = date.today()
        if value > today:
            raise ValueError("Date of birth can't be in the future")
        if today.year - value.year > MAX_PLAUSIBLE_AGE:
            raise ValueError("Date of birth is implausibly far in the past")
        return value


class ProfileOut(BaseModel):
    display_name: str | None = None
    mobile_number: str | None = None
    date_of_birth: date | None = None
    country_region: str | None = None
    travel_frequency: str | None = None
    pace: str | None = None
    budget_tier: str | None = None
    interests: list[str] = []
    travel_companions: str | None = None
    typical_trip_length_days: int | None = None
    dietary_needs: str | None = None
    accessibility_needs: str | None = None
    bucket_list_countries: list[str] = []
    additional_preferences: str | None = None
    onboarding_completed_at: datetime | None = None
    onboarding_skipped_at: datetime | None = None


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


class PassportStampOut(BaseModel):
    """One per real (non-edit-regenerated) Trip row -- see
    stats_service.compute_trip_stats' is_edit filtering. accent is a
    passport_service.STAMP_PALETTE name, not a hex value, so the frontend
    controls the actual color tokens."""

    trip_id: int
    destination: str
    accent: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AchievementOut(BaseModel):
    code: str
    label: str
    description: str
    tier: str
    earned_at: datetime


class PassportOut(BaseModel):
    """GET /gamification/passport's full response -- level is always
    computed (gamification_service.level_for_xp), never stored.
    newly_unlocked lists only codes awarded during *this* request (see
    gamification_service.evaluate_and_award), so the frontend can toast
    "badge unlocked" without re-showing it on every later visit."""

    level: int
    xp_points: int
    trip_count: int
    distinct_destinations: int
    countries_visited: list[str]
    stamps: list[PassportStampOut]
    achievements: list[AchievementOut]
    newly_unlocked: list[str] = []
