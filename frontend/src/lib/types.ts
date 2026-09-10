// TypeScript mirrors of backend/app/schemas.py. Keep these in sync by hand --
// there's no shared schema generation between the two languages yet.

export interface ItineraryItemOut {
  day_number: number;
  time_of_day: string | null;
  activity: string;
  notes: string | null;
}

export interface DayWeatherOut {
  day_number: number;
  date: string; // ISO date
  temp_min: number;
  temp_max: number;
  temp_min_f: number;
  temp_max_f: number;
  condition: string;
}

// Mirrors schemas.SavedPlaceOut -- a place find_nearby_places/
// get_place_details actually surfaced for a trip, auto-persisted with no
// manual "save" action (see models.SavedPlace).
export interface SavedPlaceOut {
  name: string;
  address: string | null;
  rating: number | null;
  price_level: string | null;
}

// Mirrors schemas.EventOut -- a real Ticketmaster event for the trip's
// destination/date window (events_service.py). All fields optional --
// Ticketmaster doesn't guarantee every field for every event.
export interface EventOut {
  event_id: string | null;
  name: string | null;
  date: string | null;
  time: string | null;
  venue: string | null;
  segment: string | null;
  genre: string | null;
  price_min: number | null;
  price_max: number | null;
  url: string | null;
}

export interface TripResponse {
  trip_id: number | null;
  destination: string | null;
  itinerary: ItineraryItemOut[];
  note: string | null;
  agent_context: string | null;
  conversation_id: number | null;
  reply: string | null;
  weather: DayWeatherOut[];
  start_date: string | null; // ISO date, or null if unresolved -- gates .ics export
  saved_places: SavedPlaceOut[];
  events: EventOut[];
}

export interface MessageOut {
  id: number;
  role: "user" | "assistant";
  content: string;
  trip: TripResponse | null;
  created_at: string;
}

// Mirrors schemas.TripSummary -- the "Your Trips" list, deliberately
// smaller than TripResponse (no itinerary/weather payload). `status` is
// derived server-side (trip_status.py), never guessed client-side.
export interface TripSummary {
  id: number;
  destination: string;
  start_date: string | null; // ISO date, or null for a draft
  day_count: number;
  status: "draft" | "upcoming" | "completed";
  created_at: string;
  // Both null when PEXELS_API_KEY is unset or the search found nothing --
  // TripCard falls back to a flat color banner, never a broken image.
  photo_url: string | null;
  photo_credit: string | null;
}

export interface ConversationSummary {
  id: number;
  title: string;
  created_at: string;
  // Latest Trip id generated in this conversation, if any -- lets the
  // sidebar route straight to that trip's Trip Hub page. Null for a
  // conversation with no generated itinerary yet.
  trip_id: number | null;
}

// Mirrors schemas.ProfileOut -- onboarding answers used to personalize
// itinerary generation (see backend/app/models.py's UserProfile).
export interface Profile {
  display_name: string | null;
  mobile_number: string | null;
  date_of_birth: string | null; // ISO date
  country_region: string | null;
  travel_frequency: string | null;
  pace: string | null;
  budget_tier: string | null;
  interests: string[];
  travel_companions: string | null;
  typical_trip_length_days: number | null;
  dietary_needs: string | null;
  accessibility_needs: string | null;
  bucket_list_countries: string[];
  additional_preferences: string | null;
  onboarding_completed_at: string | null;
  onboarding_skipped_at: string | null;
}

// Mirrors schemas.ProfileUpdate -- every field optional, since the
// onboarding form is fully skippable and a single-field edit from Profile
// reuses this same shape.
export interface ProfileUpdate {
  display_name?: string | null;
  mobile_number?: string | null;
  date_of_birth?: string | null; // ISO date
  country_region?: string | null;
  travel_frequency?: string | null;
  pace?: string | null;
  budget_tier?: string | null;
  interests?: string[] | null;
  travel_companions?: string | null;
  typical_trip_length_days?: number | null;
  dietary_needs?: string | null;
  accessibility_needs?: string | null;
  bucket_list_countries?: string[] | null;
  additional_preferences?: string | null;
}

// Mirrors schemas.PassportStampOut/AchievementOut/PassportOut -- gamification
// (see backend/app/routers/gamification.py). accent is a
// passport_service.STAMP_PALETTE name, not a hex value -- the frontend maps
// it to real color tokens.
export interface PassportStamp {
  trip_id: number;
  destination: string;
  accent: string;
  created_at: string;
  // True whenever the trip's completion can't be proven from a real
  // date -- never guessed True just because none was given.
  in_progress: boolean;
}

export interface Achievement {
  code: string;
  label: string;
  description: string;
  tier: "Common" | "Rare" | "Epic" | "Legendary";
  earned_at: string;
}

export interface Passport {
  level: number;
  xp_points: number;
  trip_count: number;
  distinct_destinations: number;
  countries_visited: string[];
  stamps: PassportStamp[];
  achievements: Achievement[];
  // Codes awarded during the request that produced this Passport -- only
  // meaningful right after the fetch that returned it, never re-derived
  // from a stale copy.
  newly_unlocked: string[];
}

export interface ConversationDetail {
  id: number;
  title: string;
  created_at: string;
  messages: MessageOut[];
  tour_guide_mode: boolean;
}
