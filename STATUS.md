# STATUS — Itinera

Current snapshot. For why things are the way they are, see
[`decisions.md`](decisions.md). For the session-by-session history behind
this snapshot, see [`progress.md`](progress.md).

_Last rebuilt: 2026-09-02, consolidating everything documented up to that
date into this four-file structure (README/STATUS/decisions/progress).
Last updated: 2026-09-02, after the `.gitignore` fixes and the palette
research pass (see `progress.md`'s 2026-09-02 entry for both)._

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

**Frontend**: Next.js (App Router, TS), Tailwind v4 + shadcn/ui, teal
brand palette with an amber tour-guide-mode accent — **currently under
active review**, not settled. Four alternative palette directions are
published (see `docs/design-references.md`'s Palette Directions page);
none chosen yet. A real gap found during that review: tour-guide mode
today only recolors the user's own chat bubble (`ChatMessage.tsx`'s
assistant bubble is always plain `bg-card`) — not yet fixed in the actual
component. No native/PWA app exists yet — see `docs/design-references.md`'s
UX Directions canvas for an unbuilt mockup of what one could look like.

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
| Persistent tour-guide mode | Live |
| Google OAuth login + per-user data isolation | Live (needs a real `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` to actually sign in) |
| Google Calendar push ("Export Plan") | Live |
| Currency conversion (`gather_trip_context`/`convert_currency`) | **Paused** — product decision, not a bug. Kill switch: `AGENT_TOOL_CALLING_ENABLED` |
| Groq fallback | Live, verified |
| Flights (tracking/predicting/booking) | Not built — deep-link booking scoped, price tracking blocked on a verified free data source |
| Hotels | Not built |
| Maps/routing | Not built — planned around Google's Maps MCP server |
| Cross-trip preference memory (pgvector) | Not built — deliberately last |
| PDF export | Deferred indefinitely |

## Next action

Three candidates, none started:
1. **Pick a palette direction** (see `docs/design-references.md`) and wire
   it into `globals.css` + fix the tour-guide assistant-bubble gap in
   `ChatMessage.tsx` — the smallest, most self-contained of the three.
2. Build-order item 4: Maps/routing.
3. Resolve the flight price-tracking data-source question
   (Travelpayouts/Aviasales — unverified).

## Known blockers / open items

- **No palette direction chosen yet** — four researched candidates exist
  (Ocean & Golden Hour/current, Terracotta & Sage, Dusk City, Trail &
  Canyon); only Direction A uses the app's real, verified color values,
  the other three are first-pass oklch estimates that need a real WCAG
  contrast check before shipping.
- **Tour-guide mode's chat-bubble treatment is incomplete** — only the
  user's own bubble recolors today; the assistant's tour-guide replies
  look identical to a normal reply. Fix is designed (a soft accent tint)
  but not applied to `ChatMessage.tsx` yet.
- **Google OAuth consent screen is still in "Testing" status** — caps
  refresh tokens at 7 days. Publishing to Production needs a human in
  Google Cloud Console; explicitly deferred until there's a real domain
  to publish against (see `decisions.md`'s Deployment entry).
- **No native/PWA app exists** — the "App" mockups in the UX Directions
  canvas assume one; that's a real engineering decision (React Native vs.
  PWA vs. native) not yet made.
- **No user research behind the current UX direction** — built from
  feature docs and engineering history, not measured usage.
- CI on `main` is green (fixed a `pytest` import bug that had been broken
  since 2026-08-31).
