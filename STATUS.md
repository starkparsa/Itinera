# STATUS — Itinera

Current snapshot. For why things are the way they are, see
[`decisions.md`](decisions.md). For the session-by-session history behind
this snapshot, see [`progress.md`](progress.md).

_Last rebuilt: 2026-09-02, consolidating everything documented up to that
date into this four-file structure (README/STATUS/decisions/progress).
Last updated: 2026-09-04, after Trip Hub v2, Saved Places, Pexels trip
photos, and Ticketmaster event discovery were all wired into the real
app, plus three same-day chat/Trip-Hub layout fixes: the chat header and
composer locked in place with only the message list scrolling, the Day
accordion cards actually animating shut (missing keyframes) instead of
snapping, and the Trip Hub chat column filling available width instead
of leaving dead space next to the side panel (see `progress.md`'s
2026-09-04 entries). Updated again same day after a frontend UI/UX pass
(PR #24): sidebar delete confirmation, a retryable error/loading state
in `ChatApp` and across the two Trip Hub routes, an overlay drawer for
the sidebar on mobile, and a first accessibility pass (skip link,
`aria-live` transcript, focus management). Updated once more same day
(PR #27) after a real WCAG AA contrast check on the Dusk City palette
(caught and fixed two failures in light-mode tour-guide mode) and a
follow-up accessibility pass (announced status messages, a screen-reader
speaker cue in chat, `aria-current` on the active conversation, a
labeled composer) — see `decisions.md`'s UI styling entries and
`progress.md`'s 2026-09-04 entries._

## Where the project stands

**Product**: a chat-driven AI trip planner. Describe a trip, get a
day-by-day itinerary, refine it conversationally, export it to Google
Calendar. Full scope (weather, place context, calendar push, per-user
accounts) — done. Maps/routing, flights, hotels, cross-trip memory — not
started.

**Backend**: FastAPI + SQLAlchemy, Postgres on Neon. Every request goes
through one router (`POST /trips/generate`) — see `decisions.md`'s
Architecture entry for the flow, or the published
[request-flow diagram](design-references.md) for a visual trace.

**Frontend**: Next.js (App Router, TS), Tailwind v4 + shadcn/ui, now
running the **Dusk City palette live** (indigo primary, copper tour-guide
accent) in `globals.css` — both chat bubbles tint on tour-guide mode now,
not just the user's own (a real gap found during the earlier palette
review, fixed as part of this integration). **Trip Hub v2 is live**: a
collapsible conversation sidebar (closed by default) on the main chat, a
new `/trips` page (real trip cards — status pill, day count, a real
per-city photo), and a new `/trips/[tripId]` Trip Hub page (the existing
chat reused via `ChatApp`'s new `initialConversationId`/`rightPanel`
props, plus a collapsible data column with Weather and Saved Places
cards) — the chat column there now fills whatever width the row gives it
next to that panel, instead of sitting in a fixed-width column with dead
space beside it. The earlier "City Passport" (travel-document/boarding-pass)
direction stays a rejected dead end, not touched. A same-day UI/UX pass
added: a real confirm dialog before deleting a chat; a retryable
error/loading state in `ChatApp` (`PendingState`/`ErrorState` unions,
replacing ad hoc booleans) and — separately — in `listTrips()`/`getTrip()`,
which used to fail open to `[]`/`null` and render "no trips"/404 on a
plain network blip; an overlay `Sheet` drawer for the sidebar on mobile
instead of a full-width block that pushed the composer off-screen; and a
first accessibility pass (skip link, `aria-live` on the message
transcript, focus returning to the composer after a send, `#main-content`
landmarks). A same-day follow-up (PR #27) ran a real oklch->sRGB contrast
check on the Dusk City palette — found and fixed two AA failures, both
in light-mode tour-guide mode (the copper accent was darkened from
`oklch(0.58 0.15 55)` to `oklch(0.45 0.15 55)`) — plus a second
accessibility pass (announced status messages, a screen-reader speaker
cue in chat, `aria-current` on the active conversation, a labeled
composer). No native/PWA app exists yet.

**LLM**: Gemini API (`gemini-3.5-flash-lite`), Groq as an automatic
fallback on rate-limit only. Not wired into the agentic tool-calling
loops, only into `llm_service.py`'s direct calls (classifier, generation,
plain Q&A).

## Live vs. paused right now

| Capability | State |
|---|---|
| Itinerary generation (chunked, Gemini structured output) | Live |
| Intent classification (4-way: new_trip/edit_trip/question/off_topic) | Live |
| Real per-day weather (Open-Meteo, direct call, never an LLM tool) | Live |
| Wikipedia place context (`get_place_context`) | Live, free |
| Google Places tools (`get_place_details`, `find_nearby_places`) | Live, billed — key set |
| Saved Places (auto-persisted `find_nearby_places`/`get_place_details` results) | Live — shown on the Trip Hub page, only once a place has actually been found |
| Event discovery (`find_events`, Ticketmaster) | Live, free tier — key set. On-demand only; a committed-to event can set a trip's `start_date` (2 days before, for settle-in time), but only on explicit commit phrasing |
| Persistent tour-guide mode | Live, both chat bubbles now recolor |
| Trip photos (Pexels, "{destination} skyline at night" first, plain name as fallback) | Live, billed-free tier — key set |
| Your Trips / Trip Hub pages (`/trips`, `/trips/[tripId]`) | Live |
| Google OAuth login + per-user data isolation | Live (needs a real `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` to actually sign in) |
| Google Calendar push ("Export Plan") | Live |
| Currency conversion (`gather_trip_context`/`convert_currency`) | **Paused** — product decision, not a bug. Kill switch: `AGENT_TOOL_CALLING_ENABLED` |
| Groq fallback | Live, verified |
| Flights (tracking/predicting/booking) | Not built — no backend data source exists at all; deep-link booking scoped, price tracking blocked on a verified free data source |
| Hotels | Not built |
| Maps/routing | Not built — planned around Google's Maps MCP server |
| Cross-trip preference memory (pgvector) | Not built — deliberately last |
| PDF export | Deferred indefinitely |

## Next action

Trip Hub v2, Saved Places, Pexels trip photos, Ticketmaster event
discovery, and the frontend UI/UX + accessibility/contrast pass are all
done — none of the three next candidates below depend on any of it:
1. Build-order item 4: Maps/routing (planned around Google's Maps MCP
   server — the specific server/pricing/auth details need re-confirming
   live before writing code, per `decisions.md`'s Maps/routing entry).
2. Resolve the flight price-tracking data-source question
   (Travelpayouts/Aviasales — unverified). Flight tracking is the one
   Trip Hub card still with zero backend data behind it.
3. No frontend surface for events exists yet — `find_events` and
   event-anchored dates are backend/conversational only so far (same as
   Saved Places was before its Trip Hub panel card); a dedicated Events
   card on the Trip Hub page, mirroring Saved Places', is the natural
   next step whenever that's wanted.

## Known blockers / open items

- **Flight tracking has no backend data source at all** — the one Trip
  Hub card still genuinely unbuilt, not merely unwired.
- **Google OAuth consent screen is still in "Testing" status** — caps
  refresh tokens at 7 days. Publishing to Production needs a human in
  Google Cloud Console; explicitly deferred until there's a real domain
  to publish against (see `decisions.md`'s Deployment entry).
- **No native/PWA app exists** — a real engineering decision (React
  Native vs. PWA vs. native) not yet made.
- **No user research behind the current UX direction** — built from
  feature docs and engineering history, not measured usage.
- CI on `main` is green (fixed a `pytest` import bug that had been broken
  since 2026-08-31).
