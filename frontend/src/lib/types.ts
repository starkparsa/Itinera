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
}

export interface ConversationDetail {
  id: number;
  title: string;
  created_at: string;
  messages: MessageOut[];
  tour_guide_mode: boolean;
}
