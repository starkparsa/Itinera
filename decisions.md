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

**Palette: Direction C, "Dusk City," chosen 2026-09-03** — indigo primary
(`oklch(0.45 0.11 265)`) + copper tour-guide accent
(`oklch(0.58 0.15 55)`), replacing the teal/amber pair above. Picked from
four researched directions in `docs/design-references.md`'s Palette
Directions artifact for a travel-evocative feel without going literally
nature- or city-photograph-themed. *Not yet wired into `globals.css` —
still mockup-only as of this writing.* Every mockup built after this point
uses hue-locked neutrals derived from the same 265° hue rather than plain
grey, deliberately, not just for these mockups but as the pattern to carry
into the real tokens.

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
Implemented as a `display: none` toggle, not `width: 0` — the latter was
tried first and silently broke the responsive stacked layout (collapsed
content still claimed a full row's height). *Revisit: if this needs to
become a persisted-per-user preference rather than always-collapsed-by-
default, that's real state (localStorage or `User` row), not a CSS
default.*

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
