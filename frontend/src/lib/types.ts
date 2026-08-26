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
}

export interface MessageOut {
  id: number;
  role: "user" | "assistant";
  content: string;
  trip: TripResponse | null;
  created_at: string;
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
}
