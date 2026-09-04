# Decisions — Itinera

What was decided, why, and when to revisit. Consolidated 2026-09-02 from
what had been a single sprawling decision-log table in `CLAUDE.md`; the
full blow-by-blow incident narratives behind each entry (exact error
messages, live-verification traces) live in [`progress.md`](progress.md)
instead — this file keeps only the decision, the reason, and the trigger
to revisit.

## Architecture

**Everything routes through one endpoint, `POST /trips/generate`.**
`classify_intent` runs first and sorts every message into `new_trip` /
`edit_trip` / `question` / `off_topic` before anything expensive runs —
this is what stops plain questions from producing nonsensical fake
itineraries, and lets off-topic requests short-circuit for free.
*Revisit: if a genuinely different entry point (e.g. a dedicated
`/questions` endpoint) becomes worth the split — not needed as of this
writing.*

**Three isolated tool-calling loops, not one shared one**
(`agent_service.py`): currency (`gather_trip_context`, paused),
conversational place-context (`answer_question_with_tools`), and
planning-time place-context (`gather_place_context_for_itinerary`). Kept
separate because they have different caching semantics — currency and
planning-context are cached once per conversation forever
(`Conversation.agent_context`); conversational Q&A must run fresh every
turn since a different place can be asked about each time — and each
loop is given only its own tool schema so flipping one loop's kill switch
never exposes another loop's tool as a side effect. *Revisit: never,
without re-examining the caching-semantics argument specifically — this
was learned the hard way (see progress.md, 2026-08-27).*

**Weather is never a Gemini tool.** `weather_service.py` is called
directly by the routers on every trip. "Does this trip get a forecast"
is never a judgment call the model makes, so it costs zero tokens and
never appears in a tool schema. *Revisit: never — this is a permanent
architectural stance, not a temporary simplification.*

**Never let the LLM do date arithmetic.** `date_resolver.py` resolves
relative date phrases ("next weekend," "in two weeks") with real
`dateutil` code, not model reasoning; `current_date` is injected into
every prompt as a fact. *Revisit: never.*

**Tools return small, flat, pre-aggregated JSON, never raw provider
payloads.** Applies to every integration (currency, Wikipedia, Places).
A cost control once tokens cost real money, not just tidiness.

## LLM provider

**Mistral (local) → Gemini API, done.** Workable free tier, no card.
Model has been swapped twice on real, live-discovered problems, not
speculatively:
- `gemini-2.5-flash` (original target) 404s for new API keys →
  `gemini-3.6-flash`. That model hit a hard **20 requests/day** free-tier
  cap, confirmed via a live 429.
- `gemini-3.6-flash` → **`gemini-3.5-flash-lite`** (current), specifically
  to escape that 20/day wall — confirmed a distinct quota bucket, passed
  every mechanical check live.

*Revisit: whenever a `502`/`RESOURCE_EXHAUSTED` recurs, or before relying
on a specific free-tier RPM/TPM/RPD number — these aren't published
statically anymore, verify per-account in AI Studio.* Google's Gemma 4
open-weight models were evaluated and rejected (real structured-output
and instruction-following bugs found live) — don't re-attempt without
addressing those specifically.

**Groq as an automatic fallback**, only on Gemini's HTTP 429, only in
`llm_service.py`'s direct calls — deliberately not wired into the
tool-calling loops in `agent_service.py`, which already degrade
gracefully to `""` on any failure. Verified live end-to-end 2026-08-31.

## Database

**MySQL → Postgres on Neon, done, 2026-08-29.** pgvector lives in the
same instance for the later cross-trip preference-memory feature. No
idle-pause gotcha (unlike Supabase). Trade-off accepted: no bundled
free Auth, so auth was always going to be a separate build regardless.
`DATABASE_URL` is required with no default — a silent wrong default was
exactly what caused the MySQL/SQLite reconciliation mess that prompted
this migration (see progress.md, 2026-08-29).

## Auth

**Google OAuth, built last, per the original plan — now done.** BFF
pattern: Next.js + Auth.js owns the OAuth flow and mints a short-lived
HS256 JWT (`AUTH_BACKEND_SECRET`, shared with the backend) on every
backend call; FastAPI is a stateless resource server. `User.google_sub`
is the identity key, not email. All four phases shipped: UI parity (no
auth) → real login → per-user ownership checks on every endpoint → Google
Calendar push. *Revisit: the OAuth consent screen is still "Testing"
status (7-day refresh token cap) — publish to Production once there's a
real domain to register (see STATUS.md's blockers).*

**Calendar: `googleapiclient` directly, not the Calendar MCP server** —
reversed from an earlier plan. `google-genai`'s MCP support was still
"experimental" and the Calendar MCP server itself was gated behind a
non-GA preview program at implementation time. Also the better
architectural fit independent of that: pushing to a calendar is a
deterministic user click, never a Gemini judgment call.

## Place context: Wikipedia + Google Places

**Wikipedia-only tool shipped first** (2026-08-27), scoped down from a
fully-researched Google Maps integration that needed a billing account
with no genuinely free tier. **Extended with Google Places**
(`get_place_details`, `find_nearby_places`) on 2026-09-01 once a real,
user-supplied, billing-enabled API key existed. The two sources
deliberately don't overlap: Wikipedia stays free and covers
history/cultural-significance; Places (billed, used more sparingly per
explicit prompt guidance) covers current/practical facts (rating, hours,
price) and real nearby recommendations — something Wikipedia has no
equivalent of. `GOOGLE_PLACES_API_KEY`'s presence is itself the kill
switch, same convention as `GROQ_API_KEY`. *Revisit: if Places billing
becomes a real cost concern, or when Maps/routing (below) gets built —
confirm the two features stay non-overlapping.*

## Maps/routing — not built

Reversed twice: OSM-based stack (Nominatim/Overpass/OpenRouteService) →
Google's official Maps MCP server (once Google shipped one, bundling
weather-forecast grounding) — **unverified as of the decision**, Google's
announcement didn't disclose pricing/free-tier/auth flow. *Revisit:
confirm those three facts live before writing any code against it —
don't assume the old OSM-based design transfers.*

## Weather — resolved

Real-time, per-day, via Open-Meteo — **not** an MCP server, **not** a
Gemini tool at all (see Architecture section above). OpenWeather was
tried first and removed after proving unreliable in practice (root cause
never fully diagnosed). *Revisit: only if Open-Meteo itself starts
failing — don't reach back for OpenWeather without a new reason.*

## Currency conversion — paused, not removed

`gather_trip_context()`/`convert_currency` (Frankfurter, free) is the
currency tool-calling loop — the only tool it ever calls. Re-enabled and
verified working correctly (2026-08-25: a real Frankfurter call was
correctly folded into a grounded summary), then **paused again the next
day purely as a product decision that currency conversion isn't a needed
feature** — not a reliability finding, unlike weather above. The kill
switch (`AGENT_TOOL_CALLING_ENABLED = False`) stays specifically so this
can flip back on without rebuilding anything. *Revisit: if the product
decision changes — the code and tests are fully intact behind the flag,
this is not a pruning candidate.*

## Event discovery: Ticketmaster — live, 2026-09-04

**find_events (Ticketmaster Discovery API, free tier confirmed live:
5,000 req/day, no card) added as a fourth tool**, alongside the three
place tools, reached through the same two on-demand loops
(`answer_question_with_tools`/`gather_place_context_for_itinerary`) —
not a separate always-on step, and not a new persistent interest
profile. All three scope calls confirmed with the user before building:
interests read fresh from the prompt each turn (doesn't pull the
deliberately-last cross-trip-memory/pgvector item forward); discovery is
on-demand only; an event can set a trip's `start_date`, but only on
explicit commit phrasing.

**A committed-to event's real date can set `start_date` — 2 days before
the event, for settle-in time (`event_planning.py`,
`SETTLE_IN_DAYS = 2`, a single tunable constant) — but only when the
request's own wording truly commits ("build a trip around X"), never for
a plain browsing/interest question.** Detected via a structured,
deterministic marker (`PLANNING_TOOL_SYSTEM_PROMPT` instructs the model
to emit `COMMITTED_EVENT_ID: <id>` on its own line only on genuine
commitment, `event_planning.extract_committed_event_id` regex-matches
that exact line — never fuzzy prose parsing) rather than trusting a
find_events call's mere existence, or the model's own judgment call, as
the signal — a narrow search returning one result is not the same thing
as the user having committed to it. The resolved event is always
re-fetched by id (`ticketmaster_client.get_event`) before its date is
trusted, never taken from a possibly-stale earlier tool result. Tried as
a fallback, same tier as `previous_trip.start_date`, only when the
prompt's own text didn't already resolve an explicit date — an explicit
date always wins, unchanged.

**No new `TripRequest` field, no frontend/UI change** — the whole flow
reuses this same day's Saved Places plumbing exactly: `_run_tool_loop`'s
raw tool-call results already flow up through `generate_itinerary`'s
`result["found_places"]`, so `find_events` cost nothing extra to wire
into that existing channel. *Revisit: `find_events` has no Trip Hub
panel card yet (unlike Saved Places, which got one) — purely
backend/conversational for now; adding one is the natural next step.*

**Ticketmaster's `keyword` param does literal name-matching, not genre
matching — confirmed live, not assumed.** Searching `keyword="jazz"`
returned "Miami Heat vs. Utah Jazz" (matched on the opposing team's
name, not an actual jazz show). Switched to `classificationName`
instead, confirmed live to return real genre-correct results for both a
music genre and a sport. *Revisit: never switch back to `keyword` for
interest matching without re-reading why.*

## Flights — not built

No workable free flight-pricing API exists (Amadeus self-service was
decommissioned). Scoped into three genuinely different pieces when
discussed 2026-09-02: **booking** (deep-link to Google Flights/Kayak, no
new dependency, buildable today), **price tracking** (blocked on
verifying a real free data source — Travelpayouts/Aviasales is the
current unverified candidate — plus this app has no background-job
runner at all yet, which price tracking would be the first feature to
need), **prediction** (real ML modeling needs months of accumulated price
history this app doesn't have yet; a cheap, honest version — "this fare
is X% above its own 30-day average" — is derivable from the same
tracking data with zero ML). *Revisit: live-verify Travelpayouts/Aviasales
before writing a client for it — that's the actual next step, not a
design question.*

## Hotels — not built

Search/compare only, deep-link out — real reservations need PCI-compliant
payment flows and hotel partner agreements, out of scope.

## Cross-trip preference memory — not built, deliberately last

Materially different from within-conversation memory (already have that,
via `Conversation.agent_context` and chat history). Needs pgvector (see
Database entry) and real design work; don't pull forward without a
specific reason.

## UI styling

**Tailwind CSS v4 + shadcn/ui**, replacing ~350 lines of hand-written CSS
(2026-08-29). Teal ("ocean/exploration") accent replaces both the old
bespoke Streamlit-leftover red and shadcn's default grayscale — Tailwind's
own teal-700/teal-400 oklch stops, not hand-picked. Dark mode stays
`prefers-color-scheme`-driven, no toggle, no JS theming dependency.

**Palette: Direction C, "Dusk City," chosen 2026-09-03, wired into
`globals.css` 2026-09-04** — indigo primary (`oklch(0.45 0.11 265)`) +
copper tour-guide accent (`oklch(0.58 0.15 55)`), replacing the teal/amber
pair above. Picked from four researched directions in
`docs/design-references.md`'s Palette Directions artifact for a
travel-evocative feel without going literally nature- or
city-photograph-themed. Every token (including neutrals, hue-locked to the
same 265° rather than plain grey) is now live, not mockup-only. *Revisit:
the oklch values are still first-pass estimates, not verified
Tailwind-named stops — a real WCAG AA contrast check is owed before
treating them as final.*

**The assistant's chat bubble never recolored in tour-guide mode — only
the user's own did, since only the user bubble ever rode `--primary`
directly.** Fixed 2026-09-04 alongside the palette wiring: three new
tokens (`--chat-assistant-bg`/`-border`/`-fg`, defaulting to the existing
card tokens so normal mode is pixel-unchanged) get overridden to a soft
copper tint inside the same `[data-tour-guide-mode="true"]` block that
already swaps `--primary`. No new JS state — `ChatMessage.tsx` just reads
different tokens, the existing attribute-selector mechanism does the rest.

**UI direction: "Trip Hub v2," chosen 2026-09-03, after a same-day
rejected exploration.** A "City Passport" direction — the interface framed
as a boarding-pass/travel document, with ink-stamp result cards and a
literal app "Passport" tab of past trips — was fully built (two artifacts,
kept in `docs/design-references.md` as a recorded dead end) and then
explicitly rejected by the user once seen in full. The direction that
replaced it rebuilds the original UX Directions canvas's "Trip Hub"
concept (a persistent trip-list + active-trip view, not chat-only) as
standard product UI in the Dusk City palette — flat buttons, real
city-photo thumbnails, no travel-document metaphor. *Revisit the rejection
only if the user brings the travel-document idea back up themselves —
don't re-propose a stamp/passport metaphor by default.*

**Both the trip sidebar and the Trip Hub's data-cards column are
collapsed by default, opened only on request** — the strongest form yet of
the "don't show a tool before it's been asked for" principle, extended
from individual data cards (below) to the surrounding chrome itself.
In the mockup this was `display: none` (not `width: 0`, which silently
broke the responsive stacked layout); the real implementation
(`ChatApp.tsx`/`TripHubPanel.tsx`, 2026-09-04) uses React conditional
rendering, the framework-native equivalent. *Revisit: if this needs to
become a persisted-per-user preference rather than always-collapsed-by-
default, that's real state (localStorage or `User` row), not component
state.*

**Trip Hub v2 wired into the real app 2026-09-04**: `GET /trips` (new
endpoint) + `/trips` and `/trips/[tripId]` (new frontend routes). Reuses
`ChatApp`'s existing message rendering for the Trip Hub page (via new
`initialConversationId`/`rightPanel` props) rather than building a second
chat renderer; the day-by-day itinerary is deliberately not duplicated
outside the chat stream either, for the same reason — it already renders
via `TripView` inside the message that generated it.

**`GET /trips` shows one card per conversation, not one per `Trip` row —
a real bug found and fixed the same day it shipped.** `generate_trip`
creates a brand-new `Trip` row on every `new_trip`/`edit_trip` turn (it
never updates one in place — see `edit_trip`'s own note above); the first
version of `list_trips` listed every row unfiltered, so a conversation
refined 4 times showed up as 4 duplicate cards — confirmed against a real
user's live data. Fixed by keeping only the latest `Trip` per
`conversation_id`. The first fix attempt (`GROUP BY
coalesce(conversation_id, id)`, to give conversation-less orphan trips
their own group) had its own real bug, also caught before shipping: `Trip`
and `Conversation` ids are independent sequences that can produce the same
number, so an orphan's own id could numerically collide with an unrelated
trip's real `conversation_id` and wrongly merge the two. Replaced with two
separate, unioned queries (grouped-by-conversation trips; conversation-less
trips standing alone) — structurally collision-proof rather than just
unlikely to collide. *Revisit: never revert to the single coalesced-key
form without re-reading why.*

**Never run `npx shadcn add <component>` directly in this repo — hand-port
instead, 2026-09-04.** The installed CLI (against this project's
`base-nova` custom style, Base UI not Radix) wants to overwrite
`button.tsx` unprompted and adds a stray `cn` npm package as a dependency
the project doesn't need (it already has its own `cn()` in `lib/utils.ts`).
`alert-dialog.tsx`, `sheet.tsx`, and `skeleton.tsx` were all added instead
by running `npx shadcn view <name>` (read-only, writes nothing) to pull the
registry's real Base UI + Tailwind source, then hand-copying it in with
imports pointed at this project's own `@/lib/utils`/`@/components/ui/button`
and the registry's `cn-font-heading`/app-internal icon-helper references
swapped for what this repo actually has (`font-heading`, `lucide-react`).
*Revisit: only after confirming with `--dry-run` that a future CLI version
no longer tries to overwrite existing files unprompted.*

**Retryable errors, not just error messages, 2026-09-04.** `ChatApp.tsx`'s
`error` state carries a `retry` closure alongside the message (a
`PendingState`/`ErrorState` union pair, replacing the previous separate
`pendingPrompt`/`error` booleans) so a "Try again" button can always resend
whatever actually failed — a prompt, or a conversation load — without the
UI re-deriving which action to repeat. `listTrips()`/`getTrip()` in
`backend.ts` got the matching fix on the read side: both used to fail open
to `[]`/`null` on *any* failure, so a plain network blip rendered
identically to "you have no trips" on `/trips` or a hard 404 on
`/trips/[tripId]` — they now return a typed `{ ok, notFound?, error? }`
result, and only a real backend 404 triggers `notFound()`. *Revisit: if a
third request shape is added to `ChatApp`, extend the existing unions
rather than reintroducing parallel booleans.*

**Sidebar mobile drawer uses a real JS breakpoint check (`useIsMobile`,
`useSyncExternalStore`), not a CSS-only hide, 2026-09-04.** Deciding which
of the two sidebar presentations to *mount* — an overlay `Sheet` on mobile
vs. the existing inline collapsible column on desktop, both driven by the
same `sidebarOpen` boolean — has to happen in JS: a `md:hidden` class on a
mounted-but-CSS-hidden Base UI `Dialog` would still leave it "open,"
trapping focus and scroll-locking the page behind an invisible overlay on
desktop. `useSyncExternalStore`, not `useState`+`useEffect`, avoids both
the hydration flicker and this repo's `react-hooks/set-state-in-effect`
lint error the naive version trips. *Revisit: never sidestep this with a
pure-CSS breakpoint hide for a mounted dialog/sheet elsewhere in the app.*

**The "Thinking…" staged-progress text is cosmetic, not real backend
progress, 2026-09-04.** `PendingIndicator.tsx` cycles vague labels
("Reading your trip…", "Checking the weather…") on a client-side timer
because `generateTrip()`'s call to `POST /trips/generate` is still a
single non-streaming request — the backend never tells the client which
stage (classify → generate → weather) it's actually in. Real staged
progress needs that endpoint to become a streaming one (SSE or similar);
that's a backend architecture decision, not something to fake harder on
the frontend. *Revisit: if/when streaming is added, replace the timer with
real stage events rather than layering both.*

## Saved Places (auto-persisted, no manual save action)

**Places `find_nearby_places`/`get_place_details` surface for a trip are
persisted automatically the moment the tool call succeeds — no "save this
place" button exists or is planned**, confirmed explicitly with the user
2026-09-04: building manual save would first require structured place
cards in the chat UI (places today are plain prose in the LLM's reply),
real scope beyond persistence alone. `models.SavedPlace`, deduped at the
application level on `(trip_id, name)` (not a DB unique constraint — an
edit turn re-surfacing the same place shouldn't duplicate it).

**`_run_tool_loop` (shared by all three agentic loops) now returns the raw
tool-call results alongside the reply text, not just the text.**
Filtering to "only Places-tool results become a saved place" (never
Wikipedia's `get_place_context`, never the paused currency tool) happens
at the *consumption* site (`routers/trips.py`), not inside the shared
loop — keeps that helper tool-agnostic, matching how it already stayed
agnostic about which of the three loops was calling it.

**Places found *before* a `Trip` row exists (the planning loop runs ahead
of `generate_itinerary` creating one) get threaded through
`generate_itinerary`'s existing result dict as `found_places`, persisted
only once `db.flush()` gives a real `trip.id`.** On the Q&A path, no new
`Trip` is ever created — found places attach to whatever trip already
exists in that conversation (`latest_trip`), or are simply not persisted
if none does yet; never fabricates a trip to hold a place.

## Trip photos (Pexels)

**Pexels, not a second Google Places call** — free tier confirmed live
(200 req/hr, 20,000/month, no card, per Pexels' own docs), and photography
is a different concern from place *data*, so a separate, purpose-built
client (`pexels_client.py`) mirrors `google_places_client.py`'s shape
rather than overloading the Places integration.

**Fetched once per trip, ever — no TTL, unlike weather's 3-hour cache.** A
destination's representative photo doesn't go stale the way a forecast
does; `pexels_service.get_or_refresh_trip_photo` checks only whether
`Trip.photo_url is None`, never a freshness window.

**Query tries `"{destination} city skyline at night"` first, falls back
to the plain destination name only if that returns zero results** —
requested explicitly by the user 2026-09-04 ("I want to see the city
skyline in the night for every place... only if that is not possible").
Live-verified this fallback rarely actually triggers: Pexels' search is
permissive enough to return *something* for almost any real-word query
(even "Yellowstone National Park city skyline at night" found a result),
so "not possible" in practice means a genuinely empty API response, not a
semantic judgment this integration is equipped to make — there's no
vision-based relevance check here, intentionally, matching this
codebase's general anti-fabrication stance (never guess, only use real
data or omit).

**A real schema bug caught by inspecting the live DB, not just tests**:
`main.py`'s `Base.metadata.create_all()` (a documented dev-convenience
safety net) silently created `saved_places` on a dev-server auto-reload
*before* `price_level`'s column width was corrected from `String(20)` to
`String(40)` (Google's own `priceLevel` enum values run up to 26 chars,
e.g. `PRICE_LEVEL_VERY_EXPENSIVE`) — the Alembic migration for the table
alone was silently a no-op against a DB that already had it. Caught by
directly inspecting the live schema post-migration, not by trusting the
migration's exit code; fixed with a follow-up migration. *Revisit: a
useful reminder that `create_all`'s "harmless no-op" claim only holds for
column *existence*, not column *shape* — a model change to an
already-`create_all`'d table always needs a real migration, checked
against the live schema, not assumed to have been a no-op.*

## Persistent tour-guide mode

Once triggered (explicit ask, or a physically-present narrative request —
broadened 2026-09-01 after a live misclassification bug), later `question`
turns keep the fuller narrative style by default until an
`edit_trip`/`new_trip` turn clears it. Real state
(`Conversation.tour_guide_mode`), not a per-turn model judgment. The
activating turn gets a deterministic `"Tour guide mode on."` prefix (code,
not LLM-phrased, for the same reliability reason date arithmetic stays in
code); a UI accent swap (amber) reflects it live.

## Reliability

**Groq automatic fallback** — see LLM provider section above.

## Trip length

**Inferred from the prompt, no UI field.** Explicitly rejected a
slider/number-input; say it in the message instead. Tried and
deliberately removed — don't re-add without a new reason.

## Itinerary export

**.ics only, done; PDF deferred indefinitely.** Deliberately floating
local time (no `TZID`) for the .ics file — Google's live Calendar API,
unlike the file, rejects timed events with no timezone, so the live push
path (`google_calendar.py`) resolves a real IANA timezone via
`weather_service.geocode_timezone()` and the file-export path doesn't
need to. The two-button UI (download `.ics` + separate "Connect Calendar")
was merged into one "Export Plan" button once Calendar scope got bundled
into the base login.

## Deployment (not yet executed)

**Google Cloud Run (backend) + Vercel (frontend)** chosen after a full
cost/cold-start comparison — Cloud Run's Always Free tier is a genuine
permanent allowance, not a shrinking trial, and reuses the Google Cloud
project OAuth already needs. CORS/rate-limiting/per-account daily quota
hardening already shipped ahead of an actual deploy. *Revisit: the OAuth
consent screen publish step (STATUS.md's blockers) is the one piece that
needs a human, and is deliberately not done speculatively before a real
domain exists.*

## `.gitignore` pattern anchoring — a reusable lesson

A gitignore pattern with a slash only at the *end* (`foo/`) floats and
matches at any depth; one with a slash in the *middle* (`foo/*`) anchors
to the directory the `.gitignore` file lives in and won't match a nested
`bar/foo/`. This project has hit both failure directions of that same
rule: the `lib/` shadowing incident (2026-08-26) was a floating pattern
matching too broadly and swallowing `frontend/src/lib/` from git
entirely; `graphify-out/*` (2026-09-02) was an anchored pattern matching
too narrowly and missing a nested `frontend/graphify-out/`. *Revisit:
whenever adding a new ignore pattern for something that could plausibly
exist at more than one depth in the tree — default to the floating form
(`name/`) unless there's a specific reason to anchor it.*
