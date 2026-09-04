"use server";

// Server-only bridge to the FastAPI backend -- mirrors the "frontend is a
// thin client, never calls Gemini/Groq/Open-Meteo/Frankfurter directly"
// principle from CLAUDE.md: every one of these functions is a Server Action
// (the "use server" directive above), so it only ever runs on the Next.js
// server, never in the browser, even though components call it directly.
//
// Auth (Phase B, see CLAUDE.md decision log "Auth" row): every call mints a
// short-lived, backend-scoped JWT from the current Auth.js session and
// attaches it as `Authorization: Bearer <token>`. This is a *separate* JWT
// from Auth.js's own session cookie -- the session cookie never leaves this
// server; this token carries only the minimal claims FastAPI needs
// (Google's stable `sub`, plus `email`) and is verified backend-side by
// backend/app/auth.py using a secret shared between the two services
// (AUTH_BACKEND_SECRET), never a Google token FastAPI would have to
// understand itself.

import "server-only";
import { backendAuthHeader } from "./authHeader";
import type { ConversationDetail, ConversationSummary, TripResponse, TripSummary } from "./types";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function listConversations(): Promise<ConversationSummary[]> {
  try {
    const res = await fetch(`${BACKEND_URL}/conversations`, {
      cache: "no-store",
      headers: await backendAuthHeader(),
    });
    if (!res.ok) return [];
    return await res.json();
  } catch {
    return []; // sidebar just won't update this run -- not worth blocking on, same as before
  }
}

// Unlike listConversations() above (fails open to [] -- it's a sidebar,
// losing it silently for one run is genuinely low-stakes), listTrips() and
// getTrip() below back the two Trip Hub pages' *only* content. Collapsing
// "backend unreachable" into the same empty/null shape as "you really have
// no trips"/"that trip really doesn't exist" is what let both pages show a
// confidently wrong message on a network blip -- so both now return a
// result the caller can tell apart, same ok/error shape generateTrip and
// pushTripToCalendar already use below.
export interface ListTripsResult {
  ok: boolean;
  trips: TripSummary[];
  error?: string;
}

export async function listTrips(): Promise<ListTripsResult> {
  try {
    const res = await fetch(`${BACKEND_URL}/trips`, {
      cache: "no-store",
      headers: await backendAuthHeader(),
    });
    if (!res.ok) return { ok: false, trips: [], error: `Backend returned ${res.status}` };
    return { ok: true, trips: await res.json() };
  } catch (exc) {
    return { ok: false, trips: [], error: exc instanceof Error ? exc.message : "Couldn't reach the planner backend" };
  }
}

export interface GetTripResult {
  ok: boolean;
  // Only true on a real 404 from the backend -- the caller should render a
  // genuine "not found" page. Any other failure (network error, 5xx) sets
  // `error` instead, so the caller can offer a retry rather than claim the
  // trip doesn't exist when it might just be unreachable right now.
  notFound?: boolean;
  data?: TripResponse;
  error?: string;
}

export async function getTrip(tripId: number): Promise<GetTripResult> {
  try {
    const res = await fetch(`${BACKEND_URL}/trips/${tripId}`, {
      cache: "no-store",
      headers: await backendAuthHeader(),
    });
    if (res.status === 404) return { ok: false, notFound: true };
    if (!res.ok) return { ok: false, error: `Backend returned ${res.status}` };
    return { ok: true, data: await res.json() };
  } catch (exc) {
    return { ok: false, error: exc instanceof Error ? exc.message : "Couldn't reach the planner backend" };
  }
}

export async function getConversation(conversationId: number): Promise<ConversationDetail | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/conversations/${conversationId}`, {
      cache: "no-store",
      headers: await backendAuthHeader(),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function deleteConversation(conversationId: number): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}/conversations/${conversationId}`, {
      method: "DELETE",
      headers: await backendAuthHeader(),
    });
  } catch {
    // best-effort, same as before
  }
}

export interface GenerateTripResult {
  ok: boolean;
  data?: TripResponse;
  error?: string;
}

export async function generateTrip(prompt: string, conversationId: number | null): Promise<GenerateTripResult> {
  try {
    const payload: Record<string, unknown> = { prompt };
    if (conversationId) payload.conversation_id = conversationId;

    const res = await fetch(`${BACKEND_URL}/trips/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await backendAuthHeader()) },
      body: JSON.stringify(payload),
      // Itinerary generation can take a few minutes for long trips (chunked
      // generation) -- no artificial timeout here, matches the old
      // Streamlit client's 900s timeout intent.
      cache: "no-store",
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, error: body.detail ?? `Backend returned ${res.status}` };
    }

    return { ok: true, data: await res.json() };
  } catch (exc) {
    return { ok: false, error: exc instanceof Error ? exc.message : "Couldn't reach the planner backend" };
  }
}

export interface PushToCalendarResult {
  ok: boolean;
  needsConnection?: boolean; // backend returned 428 -- prompt to connect instead of a generic error
  eventsCreated?: number;
  error?: string;
}

export async function pushTripToCalendar(tripId: number): Promise<PushToCalendarResult> {
  try {
    const res = await fetch(`${BACKEND_URL}/trips/${tripId}/push-to-calendar`, {
      method: "POST",
      headers: await backendAuthHeader(),
      cache: "no-store",
    });

    if (res.status === 428) {
      return { ok: false, needsConnection: true };
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, error: body.detail ?? `Backend returned ${res.status}` };
    }

    const body = await res.json();
    return { ok: true, eventsCreated: body.events_created };
  } catch (exc) {
    return { ok: false, error: exc instanceof Error ? exc.message : "Couldn't reach the planner backend" };
  }
}
