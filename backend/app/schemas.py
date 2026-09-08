import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Loose on purpose -- catches a name typed into the phone field or similar
# nonsense, not meant to validate real dialing-plan correctness (that's
# what actually sending an SMS would tell you, and this app doesn't send
# one yet).
_PHONE_RE = re.compile(r"^\+?[0-9\s().-]{7,20}$")
MAX_PLAUSIBLE_AGE = 120

# Same "loose on purpose" posture as _PHONE_RE -- catches obvious garbage,
# not full RFC 5322 compliance (an address that passes this but doesn't
# exist is caught by Auth.js's own "did the login actually work" flow, not
# by more regex).
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MIN_PASSWORD_LENGTH = 8

# Deliberately small and static (no external wordlist dependency, per this
# app's $0-budget/no-new-dependency-for-a-one-line-check posture) -- these
# are specifically the well-known weak passwords that would otherwise pass
# the character-class checks below (e.g. "Password1!" satisfies "has an
# uppercase letter, a digit, a special character" while being one of the
# first guesses in any real credential-stuffing attempt). Checked
# case-insensitively against the raw password, not a substring match.
_COMMON_WEAK_PASSWORDS = frozenset(
    {
        "password1!", "password123!", "password!1", "passw0rd!",
        "qwerty123!", "qwerty1!", "welcome1!", "welcome123!",
        "admin123!", "admin1!", "letmein1!", "iloveyou1!",
        "monkey123!", "dragon123!", "sunshine1!", "princess1!",
        "football1!", "baseball1!", "trustno1!", "abc12345!",
        "changeme1!", "changeme123!",
    }
)


class RegisterRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("Enter a valid email address.")
        return value.lower()

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        # Mirrors the client-side check in components/login/LoginCard.tsx --
        # this one is the authoritative check, that one is a courtesy so a
        # user isn't round-tripped to the server just to learn "add a
        # number." Rules match the brief this was built against: length,
        # an uppercase letter, a digit, a special character.
        if len(value) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password is too long.")
        if not re.search(r"[A-Z]", value):
            raise ValueError("Password must include an uppercase letter.")
        if not re.search(r"[0-9]", value):
            raise ValueError("Password must include a number.")
        if not re.search(r"[^A-Za-z0-9]", value):
            raise ValueError("Password must include a special character.")
        if value.lower() in _COMMON_WEAK_PASSWORDS:
            raise ValueError("That password is too common. Choose something less guessable.")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str


class UserAuthOut(BaseModel):
    """Minimal identity returned by /auth/register and /auth/login -- just
    enough for Auth.js's Credentials provider to mint its own session
    (frontend/src/auth.ts); never a token or session of any kind, since
    FastAPI doesn't own sessions in this architecture (see decisions.md's
    Auth entry)."""

    id: int
    email: str


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
    # Real Ticketmaster events for the trip's destination/date window (see
    # events_service.py) -- empty when there's no destination, Ticketmaster
    # isn't configured, or nothing matched, never fabricated.
    events: list["EventOut"] = []


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


class EventOut(BaseModel):
    """A real, bookable event (Ticketmaster, via tools.find_events /
    events_service.py) for a trip's destination and date window -- see
    routers/trips.py's get_trip. All fields optional: Ticketmaster doesn't
    guarantee every field is populated for every event (e.g. price ranges
    are often absent), and this schema passes through only what's there
    rather than inventing a placeholder."""

    event_id: str | None = None
    name: str | None = None
    date: str | None = None
    time: str | None = None
    venue: str | None = None
    segment: str | None = None
    genre: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    url: str | None = None


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
