# STATUS — Itinera

Current snapshot. For why things are the way they are, see
[`decisions.md`](decisions.md). For the session-by-session history behind
this snapshot, see [`progress.md`](progress.md).

_Last rebuilt: 2026-09-02, consolidating everything documented up to that
date into this four-file structure (README/STATUS/decisions/progress).
Last updated: 2026-09-03, after the palette choice, the "City Passport"
direction (built, then rejected), and its replacement, "Trip Hub v2" (see
`progress.md`'s 2026-09-03 entry)._

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

**Frontend**: Next.js (App Router, TS), Tailwind v4 + shadcn/ui, still
running the **live** teal/amber palette in code — nothing below has been
wired into the real app yet, all of it is still at the mockup stage.
**Direction C ("Dusk City": indigo primary + copper tour-guide accent) is
chosen**, and **"Trip Hub v2" is the chosen UI direction to build from**
(see `docs/design-references.md`) — two pages (trip list, active Trip Hub)
recreating the original UX Directions canvas's "Trip Hub" concept as
standard product UI, with the trip sidebar and the Trip Hub's tools column
both collapsed by default until opened. An earlier "City Passport"
(travel-document/boarding-pass) direction was fully built and then
explicitly rejected the same day — kept in `design-references.md` as a
recorded dead end, not as a live option. A real gap found during the
palette review and still unfixed: tour-guide mode today only recolors the
user's own chat bubble (`ChatMessage.tsx`'s assistant bubble is always
plain `bg-card`) — Direction C's copper tint values for it are already
documented in `design-references.md`. No native/PWA app exists yet.

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

**Integration of the Trip Hub v2 direction into the real frontend is about
to start.** In order:
1. Wire Direction C's tokens into `globals.css`'s `--primary`/`--ring`/
   `--sidebar-primary`/`--sidebar-ring` + the tour-guide override block,
   and fix the tour-guide assistant-bubble gap in `ChatMessage.tsx` using
   the copper tint values documented in `design-references.md`.
2. Build the collapsible-sidebar / collapsible-tools-column shell from the
   Trip Hub v2 mockup into the real trip page components.
3. Build-order item 4 (Maps/routing) and the flight price-tracking
   data-source question (Travelpayouts/Aviasales — unverified) both remain
   after this, unstarted.

## Known blockers / open items

- **Neither the palette nor the Trip Hub v2 layout is wired into code
  yet** — everything described above is still mockup-only. `globals.css`
  still holds the old teal/amber values. Direction C's oklch values are
  first-pass estimates, not verified Tailwind-named stops — a real WCAG AA
  contrast check is needed before shipping.
- **Tour-guide mode's chat-bubble treatment is incomplete** — only the
  user's own bubble recolors today; the assistant's tour-guide replies
  look identical to a normal reply. Fix is designed (a soft accent tint)
  but not applied to `ChatMessage.tsx` yet.
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
