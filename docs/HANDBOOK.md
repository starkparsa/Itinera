# The Itinera Handbook

**A single, exhaustive, self-contained reference to the entire codebase —
written to be useful with no other access to this project or to Claude.**

This snapshot describes `main` at commit `74110fa` (PR #68 merged,
2026-09-10), 202 tracked files. If you're reading this later, the
codebase may have moved on — this document does not update itself.

## How to use this document, and how it relates to the other project docs

Itinera already has four living documents that evolve with every change:

- **`README.md`** — quick start: what it is, how to run it.
- **`STATUS.md`** — a snapshot of what's live/paused/not-built right now.
- **`decisions.md`** — what was decided, why, and when to revisit each
  decision.
- **`progress.md`** — a dated diary of what happened each session.
- **`CLAUDE.md`** — slim, auto-loaded project instructions for Claude
  Code sessions.

Those four keep changing. **This document does not** — it's a
point-in-time synthesis, pulling everything in those four files (plus a
direct read of every source file) into one deep, organized reference,
written the way you'd want a new engineer's onboarding packet written:
assume nothing, explain everything, don't just point somewhere else and
hope. If something in this document contradicts the live code or the
four files above, trust the code and the four files — they're the
moving target; this is the snapshot.

This document has six parts:

1. **Codebase structure** — the directory layout and how a request
   actually flows through the system, end to end.
2. **File-by-file reference** — what every source file does, its public
   functions, and what it talks to.
3. **Future direction** — what's live, what's paused, what's not built,
   why, and concrete next steps for each unbuilt item.
4. **Deployment, step by step** — local dev, and two different
   production paths.
5. **Testing, CI/CD, and security posture.**
6. **Everything else** — troubleshooting, the `product-only` branch, and
   a glossary of project-specific terms.

---

# Part 1 — Codebase Structure

## 1.1 What Itinera is

A chat-driven AI trip planner. You describe a trip in plain language
("plan a 5 day trip to Lisbon"), Gemini generates a day-by-day
itinerary, you refine it conversationally ("make it more relaxed," "add
a food-focused day"), and you can export it to Google Calendar. Under
that simple surface sits a genuinely full-featured app: per-user
accounts (Google OAuth + email/password), real-time weather, real named
restaurant/attraction recommendations (Google Places), event discovery
(Ticketmaster), trip photos (Pexels), a gamification layer (passport
stamps, tiered badges), onboarding personalization, and Postgres
row-level security.

## 1.2 Top-level directory layout

```
Itinera/
├── backend/                  FastAPI + SQLAlchemy application
│   ├── app/                  All application source
│   │   ├── routers/          FastAPI route handlers (5 files)
│   │   ├── clients/          Raw external-API wrappers (5 files)
│   │   ├── *.py              Services, business logic (23 files)
│   │   ├── main.py           App composition root
│   │   ├── models.py         SQLAlchemy ORM models (the schema)
│   │   └── schemas.py        Pydantic request/response contracts
│   ├── alembic/               Database migrations
│   │   ├── env.py
│   │   └── versions/         14 migrations, chronological
│   ├── scripts/               One-off maintenance scripts
│   ├── tests/                 33 pytest files (see Part 5)
│   ├── Dockerfile
│   ├── requirements.txt       Production dependencies
│   └── requirements-dev.txt   + pytest/httpx for testing
│
├── frontend/                  Next.js (App Router) + TypeScript
│   ├── src/
│   │   ├── app/               File-based routing (pages/layouts)
│   │   ├── components/        React components
│   │   │   ├── ui/            shadcn/ui primitives (built on @base-ui/react)
│   │   │   ├── onboarding/    Onboarding flow + profile editing
│   │   │   ├── gamification/  Passport/badges
│   │   │   └── login/         Login page card
│   │   ├── hooks/              Custom React hooks
│   │   ├── lib/                Server Actions, types, utilities
│   │   ├── auth.ts             Auth.js (next-auth v5) configuration
│   │   └── types/               TypeScript ambient type augmentation
│   ├── public/                  Static assets, PWA manifest, service worker
│   ├── Dockerfile
│   └── package.json
│
├── docs/                       Architecture diagrams, deployment guides
├── .github/workflows/ci.yml     CI: lint, test, build & push images
├── docker-compose.yml            Full local stack
├── docker-compose.share.yml      Pre-built-image variant, zero build
├── README.md / STATUS.md / decisions.md / progress.md / CLAUDE.md
└── .env.example                  Every environment variable, documented
```

## 1.3 The one architectural decision that shapes everything else

**Every user-facing action funnels through a single backend endpoint:
`POST /trips/generate`.** There is no separate `/chat` or `/messages`
endpoint. A brand-new trip request, a follow-up edit, a plain question
("what's the weather like there?"), and an off-topic message
("what's 2+2?") all hit the same route. The very first thing that route
does is classify the incoming message into one of four intents
(`new_trip`, `edit_trip`, `question`, `off_topic`) with a single, cheap
Gemini call — and only *then* does anything expensive happen. This one
design choice is why the system prompt for itinerary generation never
accidentally fires on a question, and why an off-topic message costs
almost nothing (a fixed decline string, no further LLM calls at all).

## 1.4 The BFF (backend-for-frontend) authentication pattern

Neither side of the app trusts the other's raw session state.

- **Next.js (via Auth.js/next-auth v5) is the only real OAuth client.**
  It owns the actual Google OAuth handshake, and its own session lives
  in an encrypted JWT cookie that never leaves the Next.js server.
- **FastAPI never talks to Google directly.** Every Server Action or
  server-rendered page that needs to call the backend first mints a
  brand-new, short-lived (60-second), HS256-signed JWT
  (`lib/mintBackendJwt.ts`) carrying only `sub`/`email`/`provider`,
  signed with a secret (`AUTH_BACKEND_SECRET`) that both `.env` files
  share. FastAPI's `auth.get_current_user` dependency verifies that
  JWT's signature and decodes it — that's the entirety of what the
  backend knows about "who is this."
- **A brand-new Google user is auto-provisioned on first sight** of a
  new `google_sub` claim — there's no separate "create account" step for
  Google sign-in.
- Email/password accounts go through a **separate `Credentials`
  provider** in Auth.js, whose `authorize()` callback calls the
  backend's own `/auth/login` directly (pre-session, since there's no
  JWT to mint yet), and the resulting session carries `provider:
  "credentials"` so `get_current_user` knows to look the user up by
  internal id rather than by `google_sub`.

Full sequence diagram in `docs/architecture.md` §5, reproduced in Part 2
below under `frontend/src/auth.ts`.

## 1.5 Request flow, end to end: `POST /trips/generate`

This is the single most important flow in the codebase. Read this
before reading any individual file.

```
Browser
  │  types a message, hits Send
  ▼
ChatInput.tsx (client component)
  │  calls submitPrompt() from useConversationLoader hook
  ▼
lib/backend.ts's generateTrip() — a Server Action ("use server")
  │  crosses the network from the browser
  ▼
lib/authHeader.ts's backendAuthHeader()
  │  reads the Auth.js session, mints a 60s JWT via mintBackendJwt.ts
  ▼
POST {BACKEND_URL}/trips/generate
  Authorization: Bearer <jwt>
  {"prompt": "...", "conversation_id": <id or null>}
  ▼
FastAPI: routers/trips.py's generate_trip()
  │
  ├─ auth.get_current_user (Depends) — verifies JWT, auto-provisions
  │  or looks up the User row, sets Postgres RLS session identity
  │
  ├─ usage_quota.check_and_consume_daily_quota(user, db)
  │  — 429 if the per-account daily cap is exhausted; checked FIRST,
  │  before even touching the conversation, so quota is spent
  │  deterministically regardless of what happens after
  │
  ├─ Resolve/create Conversation (ownership-scoped to this user;
  │  a brand-new one gets its title from an LLM call,
  │  llm_service.generate_conversation_title)
  │
  ├─ _build_conversation_context(conversation) — short text summary
  │  of the last few turns, for the classifier and later prompts
  │
  ├─ llm_service.classify_intent(prompt, context)
  │  — ONE Gemini call. Returns (intent, tour_guide_requested).
  │  THIS is the fork point.
  │
  ├─ intent == "off_topic"
  │    → _handle_off_topic: no LLM call, fixed decline string,
  │      persist + commit + return. Cheapest possible path.
  │
  ├─ intent == "question"
  │    → _handle_question:
  │      1. Gather grounding: cached agent_context (currency/place,
  │         reused from earlier in the conversation) + live weather
  │         (always fetched directly, never an LLM tool) +
  │         on-demand date_resolver if the question implies a date
  │      2. agent_service.answer_question_with_tools — a Gemini
  │         function-calling loop with 5 tools (Wikipedia place
  │         context, Google Places details/nearby, Ticketmaster
  │         events, Google Routes travel time). Runs FRESH every
  │         single question turn — never cached, since a different
  │         place can be asked about each time.
  │      3. Falls back to llm_service.answer_question (no tools,
  │         plain chat completion) if the tool loop returns nothing.
  │      4. Deterministically prepends "Tour guide mode on." if this
  │         turn just activated it — never LLM-worded.
  │      5. Persist + commit + return. No Trip row involved.
  │
  └─ intent in ("new_trip", "edit_trip")
       → _handle_new_or_edit_trip:
         1. conversation.tour_guide_mode = False (unconditional —
            talking about planning again always clears it)
         2. llm_service.generate_itinerary(...) — the real work:
            a. _infer_trip_meta: destination + day count, via a
               Gemini call with a strict priority order (explicit
               UI field > previously-established length in this
               conversation > the traveler's own stated typical
               trip length > the model's own guess)
            b. Concurrently (ThreadPoolExecutor): gather_trip_context
               (currency, currently paused), gather_place_context_
               for_itinerary (Wikipedia/Places background, cached
               once per conversation forever after), and
               gather_named_place_pool (a deterministic sweep of 8
               Google Places categories — restaurant, cafe, bar,
               night_club, tourist_attraction, museum, park,
               shopping_mall — so every itinerary activity can name
               a REAL venue instead of a generic description)
            c. If the planning loop found a committed-to event that
               Ticketmaster can't confirm (EVENT_NOT_FOUND marker):
               STOP here, no itinerary is written at all, tell the
               user plainly instead of substituting a generic trip
            d. Otherwise, generate the itinerary in day-range chunks
               (5 days at a time, via _generate_chunk, Gemini
               structured output) — chunking avoids quality
               degrading on long trips
            e. Substring-match the finished itinerary text against
               the named-place pool to figure out which real places
               actually got used (for persistence, next)
         3. date_resolver.resolve_trip_start_date — real dateutil
            code, never LLM arithmetic, with a priority order:
            explicit date in the prompt > a committed event's real
            date (re-fetched from Ticketmaster to avoid trusting a
            stale earlier lookup) > the previous trip's start date
         4. Create Trip + ItineraryItem rows
         5. weather_service: fetch + cache real per-day forecast
            (Open-Meteo) for the trip
         6. Persist any real places the itinerary used as SavedPlace
            rows
         7. Persist + commit + return TripResponse (destination,
            day-by-day itinerary, weather, trip_id, etc.)
  ▼
Every branch converges here: append user + assistant Message rows,
commit. This IS the memory — there's no separate chat-history store;
every later turn reconstructs context by reading these rows back.
  ▼
TripResponse JSON
  ▼
back across the Server Action boundary to the browser
  ▼
ChatShell.tsx renders the new message (and, if present, a full
TripView with the day-by-day itinerary)
```

## 1.6 The tool-calling architecture

`agent_service.py` runs **three deliberately separate** Gemini
function-calling loops, plus **one deterministic (non-LLM-decided)
sweep**:

| Loop | Purpose | Cached? | Tool schema |
|---|---|---|---|
| `gather_trip_context` | Currency conversion | Once per conversation forever | `convert_currency` only. **Currently paused** (`AGENT_TOOL_CALLING_ENABLED = False`) — a product decision, not a bug |
| `answer_question_with_tools` | Conversational Q&A | **Never** — fresh every question turn | 5 tools: `get_place_context`, `get_place_details`, `find_nearby_places`, `find_events`, `compute_travel_time` |
| `gather_place_context_for_itinerary` | Planning-time background grounding | Once per conversation forever | Same 5 tools as above |
| `gather_named_place_pool` | Named-place grounding for activities | Not cached in the same sense — runs once per fresh itinerary generation | **Not a tool-calling loop at all.** Calls `find_nearby_places` directly, once per fixed category, with no model deciding whether/how many times to call it |

They're kept genuinely separate — not one shared loop with a bigger tool
list — for two reasons: (1) their caching semantics are fundamentally
different (see the table), and (2) each loop only ever sees its own
tool schema, so flipping one loop's kill switch can never accidentally
expose another loop's tool as a side effect.

**Why the fourth one (`gather_named_place_pool`) exists and isn't just
"the planning loop trying harder":** the planning loop's own judgment
caps `find_nearby_places` at roughly 1-2 calls total, by explicit
prompt instruction — a sensible cost control for a short background
summary, but it meant most of a multi-day itinerary's dining/nightlife/
sightseeing/shopping activities had no real place to actually name. So
`gather_named_place_pool` runs unconditionally: one `find_nearby_places`
call per category (8 categories, fixed), every time an itinerary is
freshly generated — regardless of what the model would have decided on
its own. The real names it finds get folded directly into the prompt
text every chunk-generation call reads, with an explicit "use these
real names, never invent one" instruction.

## 1.7 Weather is never a tool

Worth calling out on its own: `weather_service.py` is called *directly*
by the routers on every trip — "does this trip get a forecast" is never
a judgment call the model makes. It costs zero tokens and never appears
in any Gemini tool schema. This is a deliberate, permanent architectural
stance (see `decisions.md`'s Architecture entry), not a temporary
simplification — the same logic that governs date arithmetic
(`date_resolver.py`, never LLM) and derived trip status
(`trip_status.py`, never LLM).

---

# Part 2 — File-by-File Reference

Every source file, organized by directory. Each entry: what it does,
its major functions/exports, and what it talks to.

## 2.1 Backend — `backend/app/*.py` (top-level modules)

### `app/main.py`
FastAPI app entrypoint / composition root. Loads `.env` via
`load_dotenv()` **before any sibling module imports** — critical, since
every other module reads its own config via `os.getenv()` at import
time. Retries `Base.metadata.create_all(bind=engine)` up to 10 times
(2-second delay) so a fresh SQLite/Postgres database works with zero
setup — real schema *changes* go through Alembic instead, this call is
harmless against a DB that already has every table. Configures CORS
from `ALLOWED_ORIGINS` (comma-separated allow-list, defaults to
`http://localhost:3000`), wires up `slowapi` rate limiting, and mounts
all five routers.
- **Functions**: `health()` — trivial `GET /health` liveness check.
- **Talks to**: `database.Base`/`engine`, `rate_limit.limiter`, every
  router module.

### `app/models.py`
SQLAlchemy ORM models — the entire relational schema. See §2.6 for the
full column-by-column data model. Defines `User`, `Conversation`,
`Message`, `Trip`, `ItineraryItem`, `SavedPlace`, `UserProfile`,
`GoogleCalendarCredential`, `UserStats`, `UserAchievement`.
- **Talks to**: `database.Base` only.

### `app/schemas.py`
Pydantic request/response models — the API contract layer for every
router. Includes real validators: a phone-number regex, an email
regex, a common-weak-password blacklist, password-strength rules
(`RegisterRequest`), and phone/date-of-birth bounds checks
(`ProfileUpdate`).
- **Major classes**: `RegisterRequest`, `LoginRequest`, `UserAuthOut`,
  `TripRequest`, `ItineraryItemOut`, `DayWeatherOut`, `TripResponse`,
  `TripSummary`, `EventOut`, `SavedPlaceOut`, `MessageOut`,
  `ConversationSummary`, `ProfileUpdate`, `ProfileOut`,
  `ConversationDetail`, `PassportStampOut`, `AchievementOut`,
  `PassportOut`.

### `app/database.py`
DB engine/session setup, plus the row-level-security session-identity
plumbing. Reads `DATABASE_URL` (**required** — raises `RuntimeError` at
import if unset, a deliberate fail-loud choice after a past incident
where a silent wrong default caused real data confusion) and
`APP_DATABASE_URL` (optional, falls back to `DATABASE_URL` — this is the
lower-privileged, non-`BYPASSRLS` Postgres role that real app queries
run as under RLS). Registers a SQLAlchemy `after_begin` event
(`_set_rls_context`) that runs `SELECT
set_config('app.current_user_id', :v, true)` at the start of every
transaction on Postgres, reading the value from
`session.info["rls_user_id"]` (set by `auth.get_current_user`). SQLite
gets `PRAGMA foreign_keys=ON` via an event listener plus `StaticPool`.
- **Functions**: `get_db()` — the FastAPI dependency yielding/closing a
  session, used by nearly every route.

### `app/auth.py`
JWT verification for the Next.js↔FastAPI BFF bridge. Reads
`AUTH_BACKEND_SECRET` (HS256). `get_current_user` decodes the bearer
token and branches on its `provider` claim: `"google"` (default)
auto-provisions a `User` row the first time a new `google_sub` is seen;
`"credentials"` looks up the `User.id` directly and never
auto-provisions. Also sets the RLS session identity described above.
- **Functions**: `get_current_user(authorization, db)` — the dependency
  every protected route uses.

### `app/llm_service.py`
The deterministic itinerary-generation pipeline, intent classification,
and plain Q&A — **no tool-calling here**, that's `agent_service.py`'s
job. Re-exports `gemini_client`'s model/config for backward-compatible
test-patch targets. Defines the Pydantic structured-output schemas used
with `response_schema` (`IntentResult`, `TripMeta`, `ItineraryChunk`,
etc.). `CHUNK_SIZE_DAYS = 5`. `PACE_GUIDANCE`/`PACE_VOCABULARY_NOTE`
translate pace words ("Leisurely"/"Balanced"/"Packed") into concrete
activity-count/travel-radius instructions, embedded **unconditionally**
into every chunk prompt (a real gap-fix: it used to only reach the
model through a stored profile, never through the request's own
wording).
- **Major functions**:
  - `generate_conversation_title(prompt)` — LLM-generated sidebar
    title, fails safe to a raw-prompt truncation, and (as of a recent
    fix) logs that failure instead of failing silently.
  - `classify_intent(prompt, conversation_context)` →
    `(intent, tour_guide_requested)` — fails open to `("new_trip",
    False)`.
  - `answer_question(prompt, chat_messages, agent_context,
    user_profile_note)` — plain Q&A, the tool-less fallback.
  - `_infer_trip_meta(...)` — destination/day-count inference with the
    priority order described in Part 1.
  - `_generate_chunk(...)` — one chunked LLM call producing an
    `ItineraryChunk`.
  - `generate_itinerary(prompt, requested_days, conversation_context,
    cached_agent_context, previous_total_days, user_profile_note,
    typical_trip_length_days)` — the main orchestrator described in
    Part 1's request-flow walkthrough.
  - `_call_gemini(...)`/`_call_gemini_chat(...)` — low-level Gemini
    wrappers with Groq 429-fallback baked in.
  - `_is_rate_limited`/`_describe_gemini_error` — error classification
    and actionable-message translation.
- **Talks to**: `agent_service`, `event_planning`, `gemini_client`,
  `groq_service`, `google.genai`.

### `app/agent_service.py`
The three tool-calling loops plus the deterministic sweep, described in
full in Part 1 §1.6.
- **Major functions**: `gather_trip_context`, `gather_place_context_for_
  itinerary`, `gather_named_place_pool`, `answer_question_with_tools`,
  `_run_tool_loop` (shared manual tool-calling round-trip mechanics),
  `_call_gemini_with_tools`.
- **Talks to**: `gemini_client`, `tools`, `clients.google_places_client`.

### `app/tools.py`
The LLM-callable tool implementations plus their Gemini
`FunctionDeclaration`/`Tool` schemas. Five tools total.
- **Functions**: `convert_currency`, `get_place_context` (Wikipedia),
  `get_place_details` (Google Places), `find_nearby_places` (Google
  Places, resolves `near` via `_geocode_for_places` — Open-Meteo's free
  geocoder first, Places text-search as a billed fallback),
  `compute_travel_time` (Google Routes), `find_events` (Ticketmaster),
  `_trim_to_cap` (deterministic truncation at a sentence/word boundary).
- **Module constants**: `CURRENCY_TOOL_SCHEMAS`, `QA_TOOL_SCHEMAS`,
  `PLANNING_TOOL_SCHEMAS` (same 5-tool list as QA), `TOOL_SCHEMAS`
  (combined, introspection-only, never passed live to any real call),
  `TOOL_FUNCTIONS` (name→callable dict).

### `app/gemini_client.py`
Shared Gemini client construction, factored out specifically to break a
circular import between `llm_service.py` and `agent_service.py`.
`GEMINI_API_KEY`, `GEMINI_MODEL` (default `"gemini-3.5-flash-lite"`),
`THINKING_CONFIG` (`ThinkingLevel.MINIMAL` — verified live to avoid a
reasoning model burning its output-token budget on invisible thinking
tokens).
- **Functions**: `to_contents(chat_messages, prompt)` — converts this
  app's stored `{"role","content"}` dicts into Gemini's `Content` list
  (`"assistant"` maps to Gemini's `"model"`); `get_client()` — a lazy
  singleton (constructed on first real use, not at import, so importing
  this module never fails without a key).

### `app/groq_service.py`
The fallback LLM provider, reached only on a real Gemini HTTP 429.
Mirrors `llm_service`'s `_call_gemini`/`_call_gemini_chat` contract
exactly so the caller doesn't need to know which one actually answered.
`GROQ_API_KEY`, `GROQ_MODEL` (default `"openai/gpt-oss-120b"`).
- **Functions**: `_call_groq`, `_call_groq_chat`, `_reasoning_kwargs`
  (sends `reasoning_effort: "low"` for `gpt-oss` models),
  `_strip_markdown_fence`, `_get_client`.
- **Talks to**: the `openai` SDK, pointed at Groq's OpenAI-compatible
  endpoint.

### `app/weather_service.py`
Real per-day forecast via Open-Meteo — deliberately **never** a Gemini
tool (see Part 1 §1.7). `MAX_FORECAST_DAYS = 16`, `CACHE_TTL = 3h`.
- **Functions**: `geocode(destination)`, `geocode_timezone(destination)`
  (used by `google_calendar.py` to resolve a real IANA timezone for
  live Calendar push), `get_daily_forecast(lat, lon, start, num_days)`,
  `summarize_for_prompt(destination, weather)`, `read_cached_weather
  (trip)` (no freshness check — a pure read), `get_or_refresh_trip_
  weather(trip, items)` (mutates `trip.weather_json`/
  `weather_fetched_at` in place; caller commits — this contract is
  reused by `events_service.py`'s cache pattern almost verbatim).

### `app/date_resolver.py`
Deterministic (regex + `dateutil`, never LLM) free-text → date
resolution. Extracts only the date-shaped substring out of a prompt,
never fuzzy-parses the whole thing (avoids a stray number elsewhere in
the sentence bleeding into the wrong field).
- **Functions**: `resolve_trip_start_date(prompt, current_date=None)`,
  `_extract_explicit_date_substring`, `_next_weekday`, `_this_weekend`,
  `_default_anchor`.

### `app/event_planning.py`
Plain date arithmetic plus structured-marker extraction from
planning-loop summaries — again, never LLM arithmetic.
`SETTLE_IN_DAYS = 2`.
- **Functions**: `extract_committed_event_id(summary_text)` — regex for
  a `COMMITTED_EVENT_ID: <id>` line; `extract_event_not_found
  (summary_text)` — regex for an `EVENT_NOT_FOUND: <text>` line;
  `resolve_start_date_for_event(event_date, settle_in_days=2)`.

### `app/events_service.py`
The Trip Hub events-card cache layer — mirrors `weather_service.py`'s
contract exactly. `CACHE_TTL = 6h`.
- **Functions**: `get_or_refresh_trip_events(trip)`, `_trip_end_date
  (trip)`.
- **Talks to**: `models`, `tools.find_events`.

### `app/calendar_export.py`
Builds downloadable `.ics` (RFC 5545) calendar files — pure formatting,
no network/LLM call at all. `DEFAULT_EVENT_DURATION = 2h`.
- **Functions**: `resolve_event_time(time_of_day)` →
  `(hour, minute) | None` (reused by `google_calendar.py` too),
  `ics_filename(destination)`, `build_trip_calendar(trip_id,
  destination, start_date, items)` → bytes.

### `app/google_calendar.py`
Google Calendar push via `googleapiclient` directly — deliberately not
routed through Gemini/MCP, since "push this trip to my calendar" is a
deterministic click, not a judgment call. `TOKEN_ENCRYPTION_KEY`,
`CALENDAR_SCOPE`. Tokens are encrypted at rest via `cryptography.
fernet`.
- **Functions/classes**: `CalendarNotConnectedError` (exception,
  mapped to a 428 response by `routers/trips.py`); `encrypt_token`/
  `decrypt_token`; `save_credentials(...)` — upsert, preserves an
  existing refresh token if a new one wasn't issued (Google only issues
  one on the first genuine consent); `_load_credentials(db, user)` —
  builds `Credentials`, refreshes if within 60 seconds of expiry,
  persists the refresh; `push_trip_to_calendar(db, user, trip)` —
  inserts one Calendar event per `ItineraryItem`, resolving the
  destination's real timezone (falls back to UTC only if geocoding
  itself fails).

### `app/gamification_service.py`
Passport stamps + tiered badges. Evaluated **on every `GET /gamification
/passport` call** (idempotent, not hooked into trip generation itself).
`XP_PER_TRIP = 10`. `ACHIEVEMENT_DEFINITIONS` — a static dict of 6
codes: `first_trip`, `three_trips`, `ten_trips`, `first_international`,
`five_countries`, `ten_countries` (tiers Common/Rare/Epic/Legendary).
- **Functions**: `level_for_xp(xp_points)` = `1 + xp_points // 100`
  (always computed, never stored — a future formula tweak needs no
  backfill migration); `_qualifying_codes(stats, home_country)`;
  `evaluate_and_award(user, db)` → `{"newly_unlocked": [...]}` — sets
  (not increments) `UserStats.xp_points`, inserts new
  `UserAchievement` rows (idempotent via the real DB unique constraint,
  not an application-level check), commits.

### `app/stats_service.py`
Trip-history stats, computed at read time — no separate running
counter anywhere. `CITY_OR_KEYWORD_TO_COUNTRY` — a roughly 90-entry
static substring lookup, deliberately non-exhaustive (documented to
silently undercount unrecognized destinations rather than guess).
- **Functions**: `infer_country(destination)` — case-insensitive
  substring match, `None` if unrecognized, never a guess;
  `compute_trip_stats(user_id, db)` →
  `{"trip_count", "distinct_destinations", "countries_visited",
  "country_count"}`, excluding any `Trip.is_edit` rows so a
  conversational tweak to an existing trip doesn't inflate the count.

### `app/passport_service.py`
Deterministic passport-stamp styling/dedup/completion logic — no DB
access of its own. `STAMP_PALETTE` — 8 named hues in the app's own
Dusk-City-adjacent palette.
- **Functions**: `accent_for_destination(destination)` — an
  MD5-hash-based deterministic palette pick (same destination always
  gets the same color, no art assets needed); `is_trip_completed
  (start_date, total_days)` — `False` whenever no real date exists
  ("no data beats a wrong answer"); `deduplicate_stamps(trips)` —
  collapses trips that share both destination AND a real matching
  `start_date` into one stamp; never collapses two dateless trips to
  the same destination (no real signal they're duplicates).

### `app/pexels_service.py`
Trip-photo cache layer — fetched **once ever** per trip, no TTL (unlike
weather; a destination's representative photo doesn't go stale the way
a forecast does). `_PHOTO_QUERY_PRIORITY = ["{destination} city skyline
at night", "{destination}"]`.
- **Functions**: `get_or_refresh_trip_photo(trip)` →
  `{"url", "credit"} | None`.
- **Talks to**: `models`, `clients.pexels_client`.

### `app/password_auth.py`
bcrypt password hashing for email/password accounts.
`MAX_PASSWORD_BYTES = 72` (bcrypt's own hard truncation limit —
rejected explicitly, upstream, in `schemas.py`, rather than silently
truncated).
- **Functions**: `hash_password(password)`, `verify_password(password,
  password_hash)` — never raises on a malformed hash, treats it as a
  mismatch instead.

### `app/rate_limit.py`
Application-level, IP-keyed flood protection via `slowapi`.
`limiter = Limiter(key_func=get_remote_address, default_limits=
["100/minute"])`. In-process/in-memory — explicitly documented as not
shared across horizontally-scaled replicas (a real, known limitation,
not an oversight).

### `app/trip_status.py`
Derives `draft`/`upcoming`/`completed` status in plain Python — never
guessed by the LLM, and there's no `status`/`end_date` column at all;
it's always computed fresh on read.
- **Functions**: `derive_status(start_date, day_count, today=None)`.

### `app/usage_quota.py`
Per-account **daily** quota on `POST /trips/generate` — DB-backed
(distinct from `rate_limit.py`'s in-memory, IP-keyed flood protection;
this one survives a restart and a horizontally-scaled deployment).
`DAILY_TRIP_GENERATION_LIMIT` env var, default `20`.
- **Functions**: `check_and_consume_daily_quota(user, db)` → bool,
  resets the counter on a new calendar day, commits **immediately**
  (durable even if the rest of the request later fails) — this is
  checked before anything else in `generate_trip`.

## 2.2 Backend — `backend/app/routers/*.py`

### `routers/trips.py`
The single request-router — the file most of Part 1 §1.5 was about.
- **Major functions**: `generate_trip(...)` — `@limiter.limit
  ("10/minute")`, the dispatcher itself; `_handle_off_topic`,
  `_handle_question`, `_handle_new_or_edit_trip` — the three named
  reply-path helpers (a 2026-09-06 structural refactor, same behavior
  as before, just extracted for readability); `list_trips(...)` —
  `GET /trips`, dedups to the latest `Trip` per conversation via two
  unioned queries; `get_trip(trip_id, ...)` — `GET /trips/{id}`,
  ownership-checked (404, not 403, on someone else's trip);
  `export_trip_calendar(trip_id, ...)` — `.ics` download;
  `push_trip_to_calendar(trip_id, ...)` — Google Calendar push, maps
  `CalendarNotConnectedError`→428 and Google API errors→502; helpers:
  `_persist_found_places`, `_build_conversation_context`,
  `_build_chat_messages`, `_summarize_itinerary`, `_age_bracket`,
  `_build_user_profile_note`.
- **Talks to**: nearly every service module (`agent_service`,
  `calendar_export`, `date_resolver`, `event_planning`,
  `events_service`, `google_calendar`, `llm_service`, `pexels_service`,
  `trip_status`, `usage_quota`, `weather_service`), plus
  `clients.ticketmaster_client` directly (to re-confirm a committed
  event's real date).

### `routers/conversations.py`
Conversation list/detail/delete. `DEFAULT_CONVERSATION_LIST_LIMIT =
100`, `MAX = 200`.
- **Functions**: `list_conversations(...)` — ownership-scoped, joins
  the latest `Trip` id per conversation; `get_conversation
  (conversation_id, ...)` — eager-loads messages→trip→items,
  refreshes weather only for the *latest* trip in that conversation;
  `purge_conversation(db, conversation)` — a reusable deletion helper
  (deletes messages first, then Trips via the ORM so their own cascades
  fire, then the conversation itself; does **not** commit — the caller
  owns the transaction), reused by both `delete_conversation` here and
  `delete_account` in `routers/auth.py`; `delete_conversation
  (conversation_id, ...)` — `DELETE /conversations/{id}`, and since
  2026-09-09, this now genuinely purges the conversation's trip(s) too
  (a reversal of the original "orphan survives" design — see Part 3).

### `routers/auth.py`
Email/password auth, the Google-Calendar-token bridge, and full
account deletion. Logs auth events (never passwords) via a module
logger.
- **Functions**: `register(request, db)` — `POST /auth/register`,
  rejects any already-used email (no cross-provider account linking);
  `login(request, body, db)` — `POST /auth/login`, `@limiter.limit
  ("5/minute")`, one deliberately generic error message for both
  wrong-password and unknown-account (doesn't leak which), a distinct
  message for a Google-only account trying password login;
  `save_google_calendar_token(request, user, db)` — `POST /auth/
  google-calendar-token`, backend-to-backend only (called from Auth.js's
  own `jwt` callback, never from the browser); `google_calendar_status
  (user, db)` — `GET /auth/google-calendar-status`; `delete_account
  (user, db)` — `DELETE /auth/account`, purges every conversation
  (reusing `conversations.purge_conversation`), any orphaned trip, the
  `UserProfile`/`GoogleCalendarCredential`/`UserStats`/
  `UserAchievement` rows, then the `User` row itself. Does **not**
  revoke the Google OAuth grant at Google's own end — local data only.

### `routers/profile.py`
Onboarding/profile CRUD. `JSON_LIST_FIELDS = ("interests",
"bucket_list_countries")`.
- **Functions**: `_get_or_create_profile(db, user)` — get-or-create with
  real `IntegrityError` race recovery (rollback + re-query if a
  concurrent request already inserted the row); `_to_out(profile,
  user)`; `get_profile(...)` — `GET /profile`; `update_profile(body,
  ...)` — `PUT /profile`, sets `onboarding_completed_at` exactly once,
  and writes `display_name` onto `User` (not `UserProfile`) so "what
  should we call you" doesn't need a second endpoint; `skip_onboarding
  (...)` — `POST /profile/onboarding/skip`.

### `routers/gamification.py`
- **Functions**: `get_passport(user, db)` — `GET /gamification/
  passport`. Calls `gamification_service.evaluate_and_award` on every
  request (safe/idempotent), builds deduped stamps via
  `passport_service.deduplicate_stamps`, and defensively filters
  achievement codes against `ACHIEVEMENT_DEFINITIONS` (so a stray/
  legacy code in the DB never crashes the response).

## 2.3 Backend — `backend/app/clients/*.py` (raw external-API wrappers)

### `clients/google_places_client.py`
Raw Google Places API (New) wrapper — **billed**. `GOOGLE_PLACES_API_
KEY`'s presence is the `PLACES_API_ENABLED` kill switch.
`functools.lru_cache` on `text_search`/`place_details` (not on
`nearby_search`, where freshness matters more).
- **Functions**: `text_search(query)`, `place_details(place_id,
  detail)`, `nearby_search(lat, lng, place_type, radius_m=1500)`
  (capped at 5 results), `_headers(field_mask)`.

### `clients/google_routes_client.py`
Raw Google Routes API (Compute Routes) wrapper — **billed**, reuses the
same `GOOGLE_PLACES_API_KEY`/Cloud project (needs separately enabling
in Cloud Console). `ROUTES_API_ENABLED`. Deliberately no caching —
travel time is at least theoretically time-varying, unlike a place's
static identity.
- **Functions**: `compute_route(origin, destination, travel_
  mode="DRIVE")` → `{"duration_seconds", "distance_meters"} | None`.
  `VALID_TRAVEL_MODES = ("DRIVE", "WALK", "BICYCLE", "TRANSIT")`.

### `clients/pexels_client.py`
Raw Pexels API wrapper — free. `PEXELS_API_KEY`/`PEXELS_API_ENABLED`.
- **Functions**: `search_photo(query)` →
  `{"url", "photographer", "photographer_url"} | None`.

### `clients/ticketmaster_client.py`
Raw Ticketmaster Discovery API wrapper — free (5,000 requests/day, no
card). Uses the `classificationName` parameter rather than `keyword`
specifically to avoid false genre matches — a real bug caught live.
- **Functions**: `search_events(city, keyword, start_date, end_date,
  size=5)` → raw event list; `get_event(event_id)` — one event's full
  raw record by id, used to re-confirm an event's authoritative date
  server-side rather than trusting an earlier, possibly-stale lookup.

### `clients/wikipedia_client.py`
Raw Wikipedia API wrapper — free, no key needed. `USER_AGENT` header
per Wikimedia's own etiquette guidelines. Cached with no TTL (static
content).
- **Functions**: `resolve_title(query, near=None)` — an opensearch
  lookup; `get_summary(title)` — a REST page/summary extract (brief);
  `get_full_extract(title)` — an Action API full plain-text extract
  (detailed).

## 2.4 Backend — Alembic migrations (`backend/alembic/`)

`env.py` inserts the backend root onto `sys.path`, imports `app.models`
for its metadata-registration side effect, and reads `sqlalchemy.url`
from the app's own `DATABASE_URL` (not a separate config file), so
every environment stays in sync automatically.

Every migration, in chronological (revision-chain) order:

1. **`5f96d91ad93a_add_users_google_sub.py`** (2026-08-26, root
   revision) — adds `users.google_sub` (unique, indexed, nullable).
2. **`f0fa120ecdf7_add_google_calendar_credentials_table.py`**
   (2026-08-26) — creates the `google_calendar_credentials` table.
3. **`65524d890048_add_conversations_tour_guide_mode.py`** (2026-08-27)
   — adds `conversations.tour_guide_mode` (boolean, server-default
   false).
4. **`98900a8d691c_add_indexes_on_foreign_key_columns.py`**
   (2026-08-31) — adds indexes on every FK column that lacked one
   (Postgres never auto-indexes a foreign key, unlike the primary key
   it points at — a real full-table-scan-per-query gap, fixed across
   `conversations.user_id`, `itinerary_items.trip_id`,
   `messages.conversation_id`, `trips.conversation_id`,
   `trips.user_id`).
5. **`4e14c7bab841_add_users_daily_request_quota_columns.py`**
   (2026-08-31) — adds `users.daily_request_count`/`daily_request_
   count_date`.
6. **`ccdfae4d6065_add_trips_photo_columns.py`** (2026-09-04) — adds
   `trips.photo_url`/`photo_credit`/`photo_fetched_at`.
7. **`26570b0251ed_add_saved_places_table.py`** (2026-09-04) — creates
   the `saved_places` table.
8. **`ea166f5a9232_widen_saved_places_price_level.py`** (2026-09-04) —
   widens `saved_places.price_level` to `VARCHAR(40)`, fixing real
   dev-DB drift where an earlier `create_all()` had built it too
   narrow.
9. **`05db88c6b402_add_user_profiles_table.py`** (2026-09-06) — creates
   the `user_profiles` table.
10. **`e75cacca6864_add_user_profiles_account_details.py`**
    (2026-09-06) — adds `mobile_number`/`date_of_birth`/
    `country_region` to `user_profiles`.
11. **`6b2dca1a5047_add_trips_events_columns.py`** (2026-09-07) — adds
    `trips.events_json`/`events_fetched_at`.
12. **`e5d15a3c544c_add_gamification_tables.py`** (2026-09-07) — adds
    `trips.is_edit`; creates `user_stats` and `user_achievements`
    (including the `UNIQUE(user_id, code)` constraint that awarding
    relies on for idempotency).
13. **`0668d9be3ecf_add_users_password_hash.py`** (2026-09-07) — adds
    `users.password_hash`.
14. **`c3a9f21b7d44_enable_row_level_security.py`** (2026-09-08,
    **current head**) — `ENABLE`+`FORCE ROW LEVEL SECURITY` and a
    `user_id`-keyed policy on 6 direct-owner tables (`conversations`,
    `trips`, `user_profiles`, `google_calendar_credentials`,
    `user_stats`, `user_achievements`), plus an `EXISTS`-subquery
    FK-hop policy on 3 tables that don't have their own `user_id`
    (`messages` via `conversations`, `itinerary_items` via `trips`,
    `saved_places` via `trips`). `users` is **deliberately excluded**
    from RLS (see Part 5's security section for why).

## 2.5 Backend — `backend/scripts/*.py`

### `scripts/migrate_to_neon.py`
A one-off, safe-to-delete-once-confirmed data-migration script
(MySQL→Postgres/Neon cutover, 2026-08-29). Copies rows in strict FK
order (`User, Conversation, Trip, Message, ItineraryItem,
GoogleCalendarCredential`) from `SOURCE_DATABASE_URL` to
`TARGET_DATABASE_URL`, then resets Postgres sequences via `setval`. Not
general-purpose — assumes empty target tables, no upsert/dedupe logic.

## 2.6 The complete data model

Every table, every column, every relationship, exactly as it exists in
`models.py` today (confirmed by direct read, not just inventory).

### `User` (`users`)
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `email` | String(255) | unique, indexed, NOT NULL |
| `google_sub` | String(255) | unique, indexed, nullable — the real auth join key, not `email` |
| `password_hash` | String(255) | nullable — bcrypt hash, null for Google-only accounts |
| `display_name` | String(255) | |
| `daily_request_count` | Integer | NOT NULL, default 0 |
| `daily_request_count_date` | Date | nullable |
| `created_at` | DateTime | |

Relationships: `trips` (→`Trip`, `cascade="all, delete-orphan"`),
`conversations` (→`Conversation`, `cascade="all, delete-orphan"`).

### `Conversation` (`conversations`)
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK→`users.id` | NOT NULL, **indexed** |
| `title` | String(255) | NOT NULL, default `"New chat"` |
| `agent_context` | Text | nullable — cached tool findings; `""` means "ran, found nothing" |
| `tour_guide_mode` | Boolean | NOT NULL, default False |
| `created_at` | DateTime | |

Relationships: `owner`→`User`; `messages`→`Message`,
`cascade="all, delete-orphan"`, ordered by `Message.id`.

### `Message` (`messages`)
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `conversation_id` | FK→`conversations.id` | NOT NULL, **indexed**, no `ondelete` clause |
| `role` | String(20) | NOT NULL — `"user"` \| `"assistant"` |
| `content` | Text | NOT NULL |
| `trip_id` | FK→`trips.id` | nullable — only set for `new_trip`/`edit_trip` turns |
| `created_at` | DateTime | |

### `Trip` (`trips`)
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK→`users.id` | NOT NULL, **indexed** |
| `conversation_id` | FK→`conversations.id` | `ondelete="SET NULL"`, nullable, indexed — a DB-level safety net only; the real delete path explicitly removes Trips first |
| `destination` | String(255) | NOT NULL |
| `prompt` | Text | the original natural-language request |
| `start_date` | Date | nullable — resolved deterministically, never guessed |
| `weather_json` / `weather_fetched_at` | Text / DateTime | cached forecast, 3h TTL |
| `photo_url` / `photo_credit` / `photo_fetched_at` | String / String / DateTime | cached Pexels photo, no TTL |
| `events_json` / `events_fetched_at` | Text / DateTime | cached Ticketmaster listing, 6h TTL |
| `is_edit` | Boolean | NOT NULL, default False, server-default `"0"` — True for a Trip row created by an `edit_trip` turn |
| `created_at` | DateTime | |

Relationships: `owner`→`User`; `items`→`ItineraryItem`,
`cascade="all, delete-orphan"`; `saved_places`→`SavedPlace`,
`cascade="all, delete-orphan"`.

### `ItineraryItem` (`itinerary_items`)
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `trip_id` | FK→`trips.id` | NOT NULL, **indexed**, no `ondelete` — relies on the Python-side cascade |
| `day_number` | Integer | NOT NULL |
| `time_of_day` | String(50) | e.g. `"morning"`, `"14:00"` |
| `activity` | Text | NOT NULL |
| `notes` | Text | |

### `SavedPlace` (`saved_places`)
A place `find_nearby_places`/`get_place_details` actually surfaced for
a trip — auto-persisted the moment a real tool call succeeds, since
there's no manual "save" affordance anywhere in the UI. Deduped at the
**application level** on `(trip_id, name)`, not a DB unique constraint.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `trip_id` | FK→`trips.id` | NOT NULL, **indexed** |
| `name` | String(255) | NOT NULL |
| `address` | String(500) | |
| `rating` | Float | |
| `price_level` | String(40) | Google Places' own enum strings, e.g. `"PRICE_LEVEL_VERY_EXPENSIVE"` |
| `source` | String(30) | NOT NULL — `"find_nearby_places"` \| `"get_place_details"` |
| `created_at` | DateTime | |

### `UserProfile` (`user_profiles`)
One row per user, created lazily on first `GET`/`PUT /profile` rather
than at signup. Every field nullable since the onboarding form is fully
skippable — a partially-filled profile is the normal case, not an edge
case.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK→`users.id` | NOT NULL, **unique** |
| `mobile_number` | String(30) | for a not-yet-built SMS reminders feature |
| `date_of_birth` | Date | feeds real age-bracket personalization |
| `country_region` | String(100) | locale hint; also the "home country" baseline for the `first_international` achievement |
| `travel_frequency` | String(30) | |
| `pace` | String(20) | `"Leisurely"` \| `"Balanced"` \| `"Packed"` |
| `budget_tier` | String(20) | |
| `interests` | Text | JSON-encoded list |
| `travel_companions` | String(30) | |
| `typical_trip_length_days` | Integer | soft default for `_infer_trip_meta` |
| `dietary_needs` / `accessibility_needs` | Text / Text | freeform |
| `bucket_list_countries` | Text | JSON-encoded list |
| `additional_preferences` | Text | freeform (climate, pets, language, noise) |
| `onboarding_completed_at` / `onboarding_skipped_at` | DateTime / DateTime | two separate timestamps, so "actually finished" ≠ "chose to skip" |
| `created_at` / `updated_at` | DateTime / DateTime | |

### `GoogleCalendarCredential` (`google_calendar_credentials`)
One row per user who has granted the Calendar OAuth scope.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK→`users.id` | NOT NULL, **unique** |
| `encrypted_access_token` / `encrypted_refresh_token` | Text / Text | NOT NULL — Fernet-encrypted at rest |
| `access_token_expires_at` | DateTime | NOT NULL |
| `created_at` / `updated_at` | DateTime / DateTime | |

### `UserStats` (`user_stats`)
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK→`users.id` | NOT NULL, **unique, indexed** |
| `xp_points` | Integer | NOT NULL, default 0 — always *set*, never incremented in place |
| `updated_at` | DateTime | |

### `UserAchievement` (`user_achievements`)
One row per `(user, achievement code)` actually earned.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK→`users.id` | NOT NULL, **indexed** |
| `code` | String(50) | NOT NULL |
| `earned_at` | DateTime | |

`UniqueConstraint(user_id, code)` — this is the real idempotency
guarantee for awarding, not an application-level check.

### FK/cascade summary — worth memorizing before touching any delete path

- **Python-level cascade (`cascade="all, delete-orphan"`)**:
  `User→Trip`, `User→Conversation`, `Conversation→Message`,
  `Trip→ItineraryItem`, `Trip→SavedPlace`.
- **DB-level `ondelete="SET NULL"`**: `Trip.conversation_id` only — a
  safety net for a raw/ad-hoc delete that skips this app's own explicit
  purge logic. The real delete path (`purge_conversation`) always
  removes every `Trip` for a conversation *before* deleting the
  conversation, so this SET NULL essentially never fires in normal
  operation.
- **No `ondelete` clause at all** (relies on strict application-level
  ordering — children before parents): `Message.conversation_id`,
  `Message.trip_id`, `ItineraryItem.trip_id`, `SavedPlace.trip_id`,
  every `UserProfile`/`GoogleCalendarCredential`/`UserStats`/
  `UserAchievement`→`users.id` FK.
- **Row-Level Security** (Postgres only): direct `user_id`-keyed policy
  on `conversations`, `trips`, `user_profiles`,
  `google_calendar_credentials`, `user_stats`, `user_achievements`; an
  `EXISTS`-subquery FK-hop policy on `messages`, `itinerary_items`,
  `saved_places`. `users` is deliberately excluded (its own unique
  constraints on `email`/`google_sub` plus bcrypt hashing plus
  `get_current_user`'s exact-match lookups already protect it — adding
  RLS there would need a *third*, bypass-capable role just for the two
  endpoints that legitimately need to touch other users' auth rows,
  which wasn't judged worth the added infrastructure).

## 2.7 The complete API surface

| Method | Path | Handler | Auth required? |
|---|---|---|---|
| `GET` | `/health` | `main.health` | No |
| `POST` | `/trips/generate` | `routers/trips.generate_trip` | Yes |
| `GET` | `/trips` | `routers/trips.list_trips` | Yes |
| `GET` | `/trips/{trip_id}` | `routers/trips.get_trip` | Yes |
| `GET` | `/trips/{trip_id}/calendar.ics` | `routers/trips.export_trip_calendar` | Yes |
| `POST` | `/trips/{trip_id}/push-to-calendar` | `routers/trips.push_trip_to_calendar` | Yes |
| `GET` | `/conversations` | `routers/conversations.list_conversations` | Yes |
| `GET` | `/conversations/{conversation_id}` | `routers/conversations.get_conversation` | Yes |
| `DELETE` | `/conversations/{conversation_id}` | `routers/conversations.delete_conversation` | Yes |
| `POST` | `/auth/register` | `routers/auth.register` | No (creates the session) |
| `POST` | `/auth/login` | `routers/auth.login` | No (creates the session) |
| `POST` | `/auth/google-calendar-token` | `routers/auth.save_google_calendar_token` | Yes (backend-to-backend only) |
| `GET` | `/auth/google-calendar-status` | `routers/auth.google_calendar_status` | Yes |
| `DELETE` | `/auth/account` | `routers/auth.delete_account` | Yes |
| `GET` | `/profile` | `routers/profile.get_profile` | Yes |
| `PUT` | `/profile` | `routers/profile.update_profile` | Yes |
| `POST` | `/profile/onboarding/skip` | `routers/profile.skip_onboarding` | Yes |
| `GET` | `/gamification/passport` | `routers/gamification.get_passport` | Yes |

## 2.8 Every backend environment variable

| Variable | Purpose | Required? |
|---|---|---|
| `DATABASE_URL` | Schema-owning Postgres connection string (Neon). **Raises `RuntimeError` at import if unset** — no default. | **Required** |
| `APP_DATABASE_URL` | Lower-privileged, non-`BYPASSRLS` role for real app queries under RLS. Falls back to `DATABASE_URL`. | Optional |
| `AUTH_BACKEND_SECRET` | HS256 secret shared with Next.js/Auth.js to verify the backend JWT. Fails loudly (500) at request time if unset. | Required (functionally) |
| `GEMINI_API_KEY` | Gemini API key. | Required for any LLM feature |
| `GEMINI_MODEL` | Model override. Default `"gemini-3.5-flash-lite"`. | Optional |
| `GROQ_API_KEY` | Groq fallback key, used only on Gemini HTTP 429. Its presence is the kill switch. | Optional |
| `GROQ_MODEL` | Model override. Default `"openai/gpt-oss-120b"`. | Optional |
| `GOOGLE_PLACES_API_KEY` | Google Places (New) + Routes API key (same project). Presence = kill switch for both. | Optional (feature-gating), **billed** |
| `PEXELS_API_KEY` | Pexels photo search. Presence = kill switch. | Optional |
| `TICKETMASTER_API_KEY` | Ticketmaster Discovery API. Presence = kill switch. | Optional |
| `TOKEN_ENCRYPTION_KEY` | Fernet key encrypting stored Calendar tokens. Raises `RuntimeError` the moment it's needed if unset. | Required for Calendar push |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | Rebuilds `Credentials` for Calendar token refresh (same client as frontend OAuth). | Required for Calendar token refresh |
| `DAILY_TRIP_GENERATION_LIMIT` | Per-account daily cap on `POST /trips/generate`. Default `20`. | Optional |
| `ALLOWED_ORIGINS` | Comma-separated CORS allow-list. Default `http://localhost:3000`. | Optional |
| `SOURCE_DATABASE_URL` / `TARGET_DATABASE_URL` | One-off `migrate_to_neon.py` script only. | Required only for that script |

`load_dotenv()` in `main.py` runs before any other import, so all of the
above can come from a repo-root `.env` in local dev; in Docker/CI, real
environment variables are expected already set (`.env` is excluded via
`.dockerignore`).

## 2.9 Frontend — `frontend/src/app/**` (App Router)

### `app/layout.tsx`
Root layout for the whole app. Loads Geist/Geist Mono fonts, sets PWA
metadata, renders a keyboard-only "Skip to main content" link, mounts
`<PwaRegister/>`, and wraps `{children}` in `<ToastProvider>`.

### `app/error.tsx`
Client component. Global App Router error boundary — logs the error,
shows an `Alert` + "Try again" calling Next's `reset()`.

### `app/not-found.tsx`
App-wide 404 page — logo, "Not found" message, link back to `/`.

### `app/(chat)/layout.tsx`
Server Component. Shared layout for the `(chat)` route group (`/` and
`/trips/[tripId]`) — the structural fix that stops `ChatShell` from
remounting on navigation between those two routes. Runs `auth()` once,
redirects to `/login` if unauthenticated, fetches `listConversations()`
+ `getProfile()` concurrently, conditionally renders `OnboardingFlow`
if the profile is incomplete and not skipped, and wraps `children` in
the persistent `ChatShell`.

### `app/(chat)/page.tsx`
Server Component — the `/` home-chat route. Resolves a `?chat=<id>`
search param, fetches `getConversation()` server-side if set, hands it
to `OpenConversation`.

### `app/(chat)/trips/[tripId]/page.tsx`
Server Component — the Trip Hub page. Fetches `getTrip(tripId)`; calls
`notFound()` on a real 404, renders `RouteErrorState` on other
failures. Also fetches `getConversation()` for that trip's conversation
in the same round trip, then renders `OpenConversation` plus
`TripHubPanel`.

### `app/(chat)/trips/[tripId]/loading.tsx`
Route-level Suspense fallback for just this segment's own data (since
`ChatShell` is already mounted persistently) — a small skeleton.

### `app/api/auth/[...nextauth]/route.ts`
Wires Auth.js's `GET`/`POST` handlers into the App Router's catch-all
`/api/auth/*` route.

### `app/login/actions.ts`
Server Actions for the login page. `googleSignIn()` triggers the Google
OAuth flow. `emailSignUp`/`emailLogin` call the backend's `/auth/
register`/`/auth/login` REST endpoints **directly** (not via
`lib/backend.ts`, since these run pre-authentication) for a specific
error message, then call `signIn("credentials", ...)` to actually
establish the Auth.js session. `extractErrorMessage()` normalizes
FastAPI's two different error-detail shapes (plain string vs. Pydantic
422 array).

### `app/login/page.tsx`
Server Component — `/login`. Redirects an already-authenticated user to
`/`; otherwise renders `LoginCard`.

### `app/profile/page.tsx`
Server Component — `/profile`. Redirects unauthenticated users;
fetches `getProfile()` + `getPassport()` concurrently; renders account-
details/trip-style/habits/goals sections, `PassportBadges`,
`ProfileEditorButton` (the edit-mode entry point into `OnboardingFlow`),
and a danger-zone section with `DeleteAccountButton`.

### `app/trips/loading.tsx` / `app/trips/page.tsx`
Route-level Suspense fallback + the real `/trips` ("Your Trips") page —
redirects unauthenticated users, calls `listTrips()`, renders
`RouteErrorState` on failure, an empty state, or a responsive grid of
`TripCard`s.

Note: `/trips` and `/profile` sit **outside** the `(chat)` route group,
so neither renders the persistent `ChatShell` — each is a standalone
page with its own `<main>`.

## 2.10 Frontend — `frontend/src/components/**`

### `components/ChatShell.tsx`
The largest and most central piece of frontend state — a client
component, persistent across `/` and `/trips/[tripId]` navigation.
Owns/exposes `ChatShellContext` (`activeConversationId`,
`openConversation(id)`, `seedConversation(id, detail)`). Delegates most
actual state logic to three extracted hooks (`useConversationLoader`,
`useSidebarOpen`, `useScrollRestore`) — the component itself is glue +
JSX. Renders `Sidebar` (inline on desktop, a `Sheet` overlay on
mobile), the message log, `ChatInput`, an error `Alert` with retry, a
header (logo, tour-guide-mode badge, "Your trips" link,
`CalendarPushButton` for the latest exportable trip), and renders
`children` (the page's own content) as a sibling. Applies/removes a
`chat-scroll-lock` class on `<html>`/`<body>` while mounted (a targeted
fix, replacing a global `overflow: hidden` that used to break scrolling
on every non-chat page).

### `components/ChatMessage.tsx`
Renders one chat bubble (user right-aligned, assistant left-aligned,
both tour-guide-mode-aware). Includes an `sr-only` speaker label for
screen readers. Renders `TripView` inline if the message has an
attached trip.

### `components/ChatInput.tsx`
Textarea + Send button composer. Enter submits (Shift+Enter for a
newline); returns focus to itself once `disabled` flips back off after
a send.

### `components/OpenConversation.tsx`
Renders nothing — an invisible bridge between a server-rendered page
(which knows which conversation to open) and the persistent
`ChatShell`. Calls `seedConversation` (zero extra client fetch) if
server-fetched data was already handed to it, else `openConversation`
(a real client fetch).

### `components/PendingIndicator.tsx`
Purely cosmetic "perceived progress" bubble while a trip-generation
request is in flight — cycles through four vague stage labels on a
timer, since the backend call is non-streaming with no real stage
information to report.

### `components/PwaRegister.tsx`
Renders nothing. Registers `/sw.js` after `window.load` (not
immediately on mount, so it never competes with first paint);
swallows registration failures silently.

### `components/RouteErrorState.tsx`
Shared presentational component for server-component routes that got a
real backend failure — an `Alert` plus a plain `<Link>` "Try again"
(re-runs the server fetch on navigation, no client JS needed).

### `components/Sidebar.tsx`
Conversation list: logo, "New chat" button, scrollable list (active one
highlighted with `aria-current`), per-conversation delete via an
`AlertDialog` confirm, and a footer with user email, "Your profile"
link, and "Sign out."

### `components/TripCard.tsx`
Card for the `/trips` grid — city photo with a credit overlay (or a
flat initials banner if no photo exists), a status badge (upcoming/
draft/completed, distinct colors), destination, start date (or "Dates
not set yet"), day count. Links to `/trips/[id]`.

### `components/TripHubPanel.tsx`
The Trip Hub's collapsible right-hand data column (Weather / Saved
Places / Events — a Flight slot is deliberately omitted, since that
feature isn't built). Collapsed by default, toggled via a chevron
button. Shows an arrival-weather card, a Saved Places card (with
ratings), an Events card (linking out to real Ticketmaster URLs), or a
"nothing fetched yet" placeholder.

### `components/TripView.tsx`
Renders a full itinerary for one message: groups items by day, shows
agent-findings/note alerts, an `Accordion` of days (each expanded by
default, with a per-day weather badge and the activity list), and a
`CalendarPushButton`.

### `components/CalendarPushButton.tsx`
"Export Plan" button — hidden entirely (not merely disabled) unless the
trip has both a `start_date` and a `trip_id`. Calls
`pushTripToCalendar`; on a `needsConnection` (backend 428) response,
triggers a re-consent fallback; otherwise shows a real success/error
status message.

### `components/onboarding/OnboardingFlow.tsx`
A 4-step onboarding/edit dialog ("Account details" → "Trip style" →
"Habits & logistics" → "Goals"), **reused unchanged** for both
first-login onboarding and the `/profile` edit flow. Uses `ChipGroup`/
`ChipOption` for single/multi-select fields. Validates phone number and
date-of-birth client-side (mirroring the backend's own authoritative
Pydantic validators). On finish, calls `updateProfile()`; on skip
(onboarding mode only), calls `skipOnboarding()`.

### `components/onboarding/ProfileEditorButton.tsx`
Bridges `/profile` (a server component) to `OnboardingFlow` in edit
mode — an "Edit preferences" button toggles local state; on completion,
calls `router.refresh()`.

### `components/onboarding/DeleteAccountButton.tsx`
The one genuinely irreversible action reachable from the UI — an
`AlertDialog` confirm, then `deleteAccount()`; on success, signs the
user out immediately; on failure, a destructive toast and the account
stays intact.

### `components/gamification/PassportBadges.tsx`
`/profile`'s gamification section: level/XP/trip-count/country-count
summary, a grid of "passport stamps" (each a link back to that trip's
Trip Hub page, colored via a mapping from the backend's `STAMP_PALETTE`
names onto app-specific CSS custom properties — not Tailwind `dark:`
classes, since this app's dark mode is media-query-driven, not
class-driven), and a list of tiered badges. Fires a "Badge unlocked"
toast once per newly-unlocked code on mount.

### `components/login/LoginCard.tsx`
The full `/login` page UI — a chip-tab Login/Signup toggle, a "Dusk
City" background (an inline SVG skyline plus a CSS gradient, no photo
asset), a real Google sign-in button, a collapsible email/password
form, client-side email/password-strength validation, and a "not
available yet" toast for the still-unbuilt password-reset link.

### `components/ui/*` — shadcn/ui primitives
All built on `@base-ui/react` + `class-variance-authority` +
`lib/utils.ts`'s `cn()`:

- **`accordion.tsx`** — used by `TripView`.
- **`alert-dialog.tsx`** — used by `Sidebar`, `DeleteAccountButton`.
- **`alert.tsx`** — used widely for errors, agent findings, notes.
- **`badge.tsx`**
- **`button.tsx`** — the app's single button primitive; **every**
  button is wired via `onClick`, never native form submission, per an
  established convention (a native `<form onSubmit>` didn't reliably
  forward through this primitive).
- **`dialog.tsx`** — used by `OnboardingFlow`.
- **`scroll-area.tsx`** — used by `Sidebar`'s chat list.
- **`separator.tsx`**
- **`sheet.tsx`** — used by `ChatShell` for the mobile sidebar overlay.
- **`skeleton.tsx`** — used in loading states throughout.
- **`textarea.tsx`** — used by `ChatInput`, `OnboardingFlow`.
- **`toast.tsx`** — `ToastProvider`/`useToast()`, this app's first-ever
  ambient-notification primitive (mounted once at `app/layout.tsx`).
  Real `role="status"` + `aria-live="polite"`, auto-dismiss after 4
  seconds. Consumers: `OnboardingFlow`, `DeleteAccountButton`,
  `PassportBadges`, `LoginCard`.
- **`toggle-chip.tsx`** — `ChipOption`/`ChipGroup`, an interactive pill
  control backed by a real, visually-hidden `<input type="checkbox"|
  "radio">` — replaced native `<select>`/checkbox lists specifically to
  fix a dark-mode native-popup contrast bug. Real form controls, so
  keyboard/screen-reader behavior comes for free.

## 2.11 Frontend — `frontend/src/hooks/*.ts`

### `hooks/use-conversation-loader.ts`
Extracted from `ChatShell.tsx`. Owns both conversation loading/caching
*and* the pending/submit/error state machine together (deliberately not
split further). A module-scope `conversationCache: Map<number,
ConversationDetail>` survives `ChatShell` remounts, with a
`loadGenerationRef` counter that discards superseded loads (guards
against React Strict Mode's double-invoke and rapid chat-switching
races).

### `hooks/use-mobile.ts`
`useIsMobile()` — a `useSyncExternalStore`-based hook subscribing to a
`(max-width: 767px)` media query, avoiding the render-then-correct
flicker a `useState`+`useEffect` version would have.

### `hooks/use-scroll-restore.ts`
Extracted from `ChatShell.tsx`. A module-scope `scrollPositionCache:
Map<number, number>`; a `useLayoutEffect` restores the remembered
scroll position when switching back to a previously-viewed
conversation, or jumps to the bottom for a new message.

### `hooks/use-sidebar-open.ts`
Extracted from `ChatShell.tsx`. `useSidebarOpen()` — a
`useSyncExternalStore`-backed read of a `localStorage` key (defaults
closed), with a same-mount in-memory override so a toggle sticks even
if another tab writes the same key concurrently.

## 2.12 Frontend — `frontend/src/lib/*.ts`

### `lib/backend.ts`
`"use server"` — the **sole** Server Actions module calling the FastAPI
backend; every call attaches an `Authorization: Bearer <JWT>` header via
`backendAuthHeader()`. Full inventory:

| Function | Backend endpoint | Response shape |
|---|---|---|
| `listConversations()` | `GET /conversations` | `ConversationSummary[]` — fails open to `[]` |
| `listTrips()` | `GET /trips` | `{ ok, trips: TripSummary[], error? }` |
| `getTrip(tripId)` | `GET /trips/{tripId}` | `{ ok, notFound?, data?, error? }` — 404 distinguished from other failures |
| `getConversation(conversationId)` | `GET /conversations/{conversationId}` | `ConversationDetail \| null` — fails open |
| `deleteConversation(conversationId)` | `DELETE /conversations/{conversationId}` | best-effort void |
| `generateTrip(prompt, conversationId)` | `POST /trips/generate` | `{ ok, data?, error? }` — no artificial timeout, since chunked generation can take minutes |
| `getProfile()` | `GET /profile` | `Profile \| null` — fails open |
| `updateProfile(update)` | `PUT /profile` | `{ ok, data?, error? }` |
| `skipOnboarding()` | `POST /profile/onboarding/skip` | same shape |
| `getPassport()` | `GET /gamification/passport` | `Passport \| null` — fails open |
| `pushTripToCalendar(tripId)` | `POST /trips/{tripId}/push-to-calendar` | `{ ok, needsConnection?, eventsCreated?, error? }` — 428 maps to `needsConnection: true` |
| `deleteAccount()` | `DELETE /auth/account` | `{ ok, error? }` |

Two more backend calls happen **outside** this file, because they run
pre-authentication or need a bespoke error shape: `app/login/
actions.ts`'s direct calls to `POST /auth/register`/`POST /auth/login`,
and `auth.ts`'s own Credentials provider / `jwt` callback.

### `lib/mintBackendJwt.ts`
`server-only`. Pure JWT signer using `jose`'s `SignJWT` — signs
`{email, provider}` claims with `sub` as the subject, HS256, 60-second
expiry, secret = `AUTH_BACKEND_SECRET` (throws if unset).

### `lib/authHeader.ts`
`server-only`. `backendAuthHeader()` — reads the current Auth.js
session, mints a backend JWT, returns `{Authorization: "Bearer
<token>"}` (or `{}` if unauthenticated/minting fails). Shared by every
`lib/backend.ts` function.

### `lib/authActions.ts`
`"use server"`. `signOutAction()` (Auth.js `signOut`, redirects to
`/login`). `connectGoogleCalendarAction()` — a re-consent fallback
(not the common path) that forces a fresh Google OAuth consent screen
with `prompt: "consent"` and the Calendar scope, used when a stored
Calendar credential has gone stale.

### `lib/types.ts`
Hand-maintained TypeScript mirrors of the backend's Pydantic schemas —
no shared codegen between the two languages.

### `lib/utils.ts`
`cn(...)` — the `clsx` + `tailwind-merge` classname combinator used
throughout every styled component.

### `lib/weatherIcon.ts`
`weatherIcon(condition)` — a keyword-matching emoji lookup, a direct
port of the old prototype's weather-icon logic.

## 2.13 `frontend/src/auth.ts` — Auth.js (next-auth v5) configuration

- **Providers**:
  1. **Google** — OAuth, scope `"openid email profile
     https://www.googleapis.com/auth/calendar.events"` bundled into the
     base login (Calendar push needs it, and asking separately later
     would be friction), `access_type: "offline"`, deliberately *not*
     `prompt: "consent"` on every login (only the genuine first grant).
  2. **Credentials** — the email/password bridge. `authorize()` calls
     the backend's `POST /auth/login`; on success returns `{id:
     String(user.id), email}`.
- **Session strategy**: `"jwt"` — Auth.js's own encrypted cookie, no
  database sessions, no second ORM.
- **Callbacks**:
  - `jwt({token, account})` — on initial sign-in only: persists
    `token.sub`/`token.provider`. For Google specifically, also mints a
    backend JWT and `POST`s the access/refresh token + expiry to
    `/auth/google-calendar-token` to persist the Calendar credential.
  - `session({session, token})` — copies `token.sub`/`token.provider`
    onto `session.user`.

## 2.14 Frontend environment variables

| Variable | Required? | Purpose |
|---|---|---|
| `BACKEND_URL` | Optional (default `http://localhost:8000`) | Base URL for all backend calls |
| `AUTH_BACKEND_SECRET` | Required for real backend calls | Shared HS256 secret |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | Required for real Google sign-in | Google OAuth client credentials |
| `AUTH_SECRET` | Required for real sessions | Encrypts the Auth.js session cookie |
| `AUTH_URL` | Optional (dev convenience) | Base URL for OAuth callback construction |

## 2.15 Config, build, and PWA files

- **`frontend/next.config.ts`**: `agentRules: false` (suppresses Next's
  auto-generated agent-instructions files — this repo has its own root
  `CLAUDE.md`), `output: "standalone"` (lean Docker image).
- **`frontend/package.json`**: Next 16.3.3, React 19.2.8, `next-auth`
  v5 beta, `@base-ui/react` (shadcn's underlying primitive library),
  Tailwind v4, `jose`, `lucide-react`, `class-variance-authority`.
- **`frontend/Dockerfile`**: three-stage build (`deps`→`builder`→
  `runner`), final image only carries `public/`, `.next/standalone`,
  `.next/static`.
- **`frontend/public/manifest.webmanifest`**: PWA manifest — name
  "Itinera", `display: "standalone"`, three icon sizes.
- **`frontend/public/sw.js`**: installable-shell-only service worker —
  caches a **fixed** list of static assets (manifest, icons, favicon)
  cache-first; everything else (pages, API calls, chat/trip data) is
  network-only, since per-user data is deliberately out of scope for
  offline caching.

---

# Part 3 — Future Direction

This section synthesizes `STATUS.md`'s live/paused table and
`decisions.md`'s not-built entries, and adds a concrete next-steps
block for each unbuilt item.

## 3.1 What's fully live

Itinerary generation, 4-way intent classification, real per-day
weather, Wikipedia place context, Google Places tools, named-place
grounding (8-category sweep), auto-persisted Saved Places, Ticketmaster
event discovery, persistent tour-guide mode, Pexels trip photos, the
`/trips`/`/trips/[tripId]` pages, Google OAuth + email/password login,
Google Calendar push, Groq fallback, onboarding personalization (with
chip/tag UI), toast notifications, the Events Trip Hub card, Postgres
row-level security, an installable-shell PWA, chat/trip deletion
(genuinely cascading as of 2026-09-09), full account deletion,
LLM-generated conversation titles, real travel-time via Google Routes,
and gamification (passport stamps + tiered badges).

## 3.2 What's explicitly paused (not a bug)

**Currency conversion** (`gather_trip_context`/`convert_currency`) —
paused via `AGENT_TOOL_CALLING_ENABLED = False` in `agent_service.py`.
Fully built and previously verified working; paused purely on a product
decision that currency conversion isn't currently a priority feature,
not because anything broke. Flip the flag back to `True` to re-enable
it with zero other code changes.

## 3.3 What's not built, and the concrete next step for each

### Maps/routing (full UI)
**Current state**: real travel-time is live (`compute_travel_time`,
Google Routes API, 2026-09-09) — verified against all four travel modes
with realistic, distinct numbers. What's still missing: turn-by-turn
directions, live traffic, and any actual map UI.
**Open question**: none blocking — Google's Maps Grounding Lite MCP
server was investigated and found real/GA for routing, but this app
deliberately built a direct REST wrapper instead (no MCP-client
infrastructure exists anywhere else in the codebase, and pulling one in
for a single tool wasn't worth the new architectural surface).
**Next steps**: (1) decide whether a map UI is worth building at all
given the app's current chat-first design — nothing about the itinerary
UI currently expects a map; (2) if yes, the existing `compute_route`
client already returns the raw route geometry-adjacent data needed as a
starting point, just not currently requested/exposed; (3) evaluate a
lightweight map rendering library (Leaflet/Mapbox GL) against the
$0-budget constraint before adding one.

### Flights
**Current state**: not built. No workable free flight-pricing API
exists today (Amadeus's self-service tier was decommissioned).
**Open question**: whether Travelpayouts/Aviasales — the one unverified
candidate data source — actually has a genuine free tier at this app's
scale.
**Next steps**: (1) **live-verify Travelpayouts/Aviasales's current
terms and free-tier limits before writing a single line of client
code** — this is explicitly the next action, not a design question;
(2) if verified, build **booking** first (a simple deep-link to Google
Flights/Kayak — no new dependency, buildable immediately, doesn't
depend on step 1 at all); (3) **price tracking** is blocked on both
step 1 and on this app having zero background-job runner — that's a
real infrastructure gap to solve first, not just an API integration;
(4) **prediction** ("this fare is X% above its own 30-day average") is
derivable from tracking data with zero ML once tracking exists — don't
attempt real ML modeling, there isn't months of price history to train
on.

### Hotels
**Current state**: not built.
**Next steps**: search/compare only, deep-link out for booking — real
reservations need PCI-compliant payment flows and hotel partner
agreements, explicitly out of scope. Same shape as Flights' booking
slice; no live-verification blocker identified yet, worth a similar
free-tier check (a hotel search API) before starting.

### Cross-trip preference memory (pgvector)
**Current state**: not built, deliberately last in the build order.
Materially different from the within-conversation memory this app
already has (via `Conversation.agent_context` and chat history).
**Open question**: no real design work has happened yet — this is the
one item with the least existing groundwork.
**Next steps**: (1) this is a genuine investigative/design task before
any code — pgvector already lives in the same Neon instance (added
specifically for this, per `decisions.md`'s Database entry), so the
infrastructure exists, but the actual design (what gets embedded, how
retrieval feeds back into `generate_itinerary`'s prompt, how it
interacts with `UserProfile`'s existing explicit preferences) doesn't;
(2) don't pull this forward without a specific reason — it was
deliberately sequenced last.

### PDF export
**Current state**: deferred indefinitely. `.ics` calendar export is the
only export format, and it's done.
**Next steps**: none currently planned — revisit only if a specific
concrete need arises.

### Spotify travel playlists
**Current state**: considered 2026-09-09, an architecture sketch
exists, explicitly not built.
**Open questions before any code**: (1) live-verify Spotify's current
Web API terms — client-credentials-flow catalog search is free, but
confirm the specific "recommendations"-style endpoint this would want
is still available under it, since Spotify's API access tiers have
changed before; (2) decide scope — suggestions-only (simple, matches
this app's existing client-credentials pattern for Places/Ticketmaster)
vs. save-to-account (would need a whole new per-user OAuth surface,
should not be assumed in scope without a separate decision).
**Next steps**: (1) do the live free-tier check first; (2) if it's
still free and scoped to suggestions-only, the tool shape is already
sketched — a thin `spotify_client.py` raw wrapper plus a `tools.py`
function returning a small flat track list (name/artist/preview link),
reached through the existing QA/planning tool-calling loops, with the
same "never invent a track" discipline every other tool already
follows.

### Reddit-sourced place info
**Current state**: considered 2026-09-09, an architecture sketch
exists, explicitly not built — flagged as the harder of the two ideas
raised that day.
**Open questions before any code**: (1) live-verify Reddit's *current*
API terms — pricing changed substantially in 2023 for higher-volume/
commercial use, and whether this app's likely call volume stays under a
genuinely free tier isn't confirmed; (2) the real, harder problem: every
other place-grounding source in this app (Wikipedia, Google Places,
Ticketmaster) is curated or structured, but Reddit comments are
unstructured opinions — sometimes wrong, sometimes stale, occasionally
in bad faith. "Ground the prompt in real data" is supposed to prevent
invented facts, but real *unreliable* data doesn't fully solve that, it
relocates the problem. No answer for this exists yet (a comment-score/
age threshold, summarizing multiple threads instead of quoting one, and
explicitly labeling it "traveler opinion, not verified fact" are the
candidate mitigations, none decided).
**Next steps**: (1) the live terms check; (2) a real design pass
specifically on the content-quality problem before writing any client
code — this is flagged as the genuinely unsolved part, not a formality.

### SMS trip-day reminders
**Current state**: `mobile_number` is collected in `UserProfile` (a
real, committed feature — this column exists because sending was
committed to, not speculatively), but the sending pipeline itself
doesn't exist.
**Next steps**: (1) live-verify a specific SMS provider's free tier,
the same discipline Travelpayouts/Aviasales still needs; (2) this app
also has no scheduling mechanism at all today (nothing runs on a timer)
— that's a real infrastructure gap this feature would be the first to
need, same shape as Flights' price-tracking blocker; (3) opt-in UX
design is a separate piece, not yet scoped.

### Shareable passport card + seasonal badges
**Current state**: considered during gamification's design research
(Duolingo/Strava badge-design literature), explicitly deferred — not
rejected on merit.
**Next steps**: revisit only if/when a social or sharing surface is
ever considered for this app at all — both ideas assume a
followers/friends graph or a $0-budget path to seasonal content
generation that doesn't exist yet, and building either without that
context first would be premature.

---

# Part 4 — Deployment, Step by Step

## 4.1 Local development (already fully working, zero cloud setup)

### Option A — Docker Compose (recommended)
```bash
cp .env.example .env
# fill in at minimum GEMINI_API_KEY
docker compose up --build
```
Frontend: `http://localhost:3000`. Backend API docs: `http://localhost:
8000/docs`. Database: whatever `DATABASE_URL` in `.env` points at
(Neon Postgres) — there's no local DB container in the default path.

### Option B — without Docker (two terminals, faster iteration)
```bash
# Terminal 1
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Terminal 2
cd frontend
npm install
npm run dev
```
For a quick run with zero external dependency at all:
`DATABASE_URL="sqlite:///./dev.db" uvicorn app.main:app --reload`.

### Option C — sharing with someone else, no build required
```bash
cp .env.share.example .env
# fill in a free GEMINI_API_KEY at minimum
docker compose -f docker-compose.share.yml up
```
Pulls pre-built images CI already publishes to GHCR on every merge to
`main` — useful for handing the app to someone with nothing but Docker
installed. Defaults to local SQLite (zero setup, no account needed).

Without a real `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET`/`AUTH_SECRET`/
`AUTH_BACKEND_SECRET`, the app still builds and runs — only real sign-in
fails at Google's own consent screen.

## 4.2 Production deploy, path 1: Cloud Run + Vercel + Neon

**Status honestly: designed and fully documented in `docs/deployment-
guide.md`, but not yet executed as of this snapshot.** No production
deploy currently exists.

**Prerequisites**: the Google Cloud project already used for OAuth (a
billing account must be attached — Cloud Run requires one on file even
to use its Always Free tier), `gcloud` CLI, Docker running locally, a
free Vercel account.

**Part 1 — Backend to Cloud Run**:
1. `gcloud auth login`, `gcloud config set project <PROJECT_ID>`,
   `gcloud config set run/region <region>`.
2. Create an Artifact Registry repo, configure Docker auth.
3. `docker build -t <registry>/backend:latest ./backend && docker push
   ...`.
4. Put every real secret (`GEMINI_API_KEY`, `GROQ_API_KEY`,
   `AUTH_BACKEND_SECRET`, `AUTH_GOOGLE_SECRET`, `TOKEN_ENCRYPTION_KEY`,
   `DATABASE_URL`) into **Secret Manager**, not plaintext
   `--set-env-vars`.
5. `gcloud run deploy itinera-backend --image ... --allow-unauthenticated
   --port 8000 --set-env-vars ... --set-secrets ...`. Leave
   `--min-instances` unset (scales to zero, stays free) unless a cold
   start is worse than a guaranteed non-zero bill.
6. `curl https://<service-url>/health` to confirm it's reachable.

**Part 2 — Frontend to Vercel**:
1. Import the repo, set **Root Directory** to `frontend/` (this is a
   monorepo).
2. Set every variable from `frontend/.env.local.example` with real
   production values — `BACKEND_URL` = the Cloud Run URL from Part 1,
   `AUTH_URL` = the real Vercel URL once known.
3. Once deployed, add the Vercel URL as an **Authorized redirect URI**
   in Google Cloud Console (`.../api/auth/callback/google`) — login
   fails with a Google-side error until this is done.

**Part 3 — Close the loop on the backend**:
1. `gcloud run services update <service> --set-env-vars ALLOWED_ORIGINS=
   https://<vercel-url>`.
2. Publish the Google OAuth consent screen (Google Cloud Console →
   OAuth consent screen → Publish App) — still in "Testing" status
   caps refresh tokens at 7 days.

**Verification checklist**: `/health` returns ok; `/` redirects to
`/login` when signed out; "Continue with Google" reaches the real
consent screen; a real trip prompt after sign-in gets a real itinerary
back; no CORS errors on `/trips/generate` in DevTools.

## 4.3 Production deploy, path 2: Cloud Run + Cloudflare Workers + Neon (beta-friendly)

**Status honestly: also fully documented (`docs/beta-deployment-
cloudflare.md`), also not yet executed.** `gcloud` CLI was installed on
the development machine this session, but the interactive
`gcloud auth login` step (a real browser OAuth flow) had not been
completed as of this snapshot.

Chosen specifically for sharing a beta with a small group of testers,
using Cloudflare instead of Vercel, while staying at genuine $0.

**Why this combination**: Cloudflare Containers — the only way to run
the FastAPI backend on Cloudflare — requires the paid Workers plan
($5/month), so the backend stays on Cloud Run regardless. Cloudflare's
own current guidance for a Next.js app with Server Actions is OpenNext
on Workers, not Cloudflare Pages (Pages' adapter only supports the Edge
runtime and doesn't fully cover Server Actions).

**Backend**: identical to path 1's Part 1.

**Frontend — Cloudflare Workers via OpenNext**:
1. `npm install @opennextjs/cloudflare@latest && npm install --save-dev
   wrangler@latest`.
2. Add `wrangler.jsonc` (main: `.open-next/worker.js`,
   `compatibility_flags: ["nodejs_compat", "global_fetch_strictly_
   public"]`, plain `vars` for non-secret config like `BACKEND_URL`).
3. Add `open-next.config.ts` (`defineCloudflareConfig()`).
4. Add `preview:cf`/`deploy:cf` npm scripts wrapping
   `opennextjs-cloudflare build` + `preview`/`deploy`.
5. **Run the local Workers preview and actually click through a real
   login + trip generation before any real deploy** — `next-auth`'s
   OAuth flow and Server Actions hadn't been exercised on the Workers
   runtime in this codebase before this guide was written; this is the
   real compatibility check, not a formality.
6. Set real secrets via `wrangler secret put <KEY>` (never in
   `wrangler.jsonc`) — `AUTH_GOOGLE_SECRET`, `AUTH_BACKEND_SECRET`
   (must exactly match the backend's own value), a **newly generated**
   `AUTH_SECRET` (`npx auth secret`, do not reuse the local dev value).
7. First deploy (`npm run deploy:cf`) prints the real Workers URL; set
   `AUTH_URL` to it via another `wrangler secret put`, redeploy.

**Close the loop on the backend**: same CORS update as path 1, pointed
at the Workers URL instead of a Vercel URL; register the same OAuth
redirect URI pattern for the new domain.

**Adding beta testers without publishing the consent screen**: Google
Cloud Console → OAuth consent screen → **Test users** → add each
tester's real Google email (up to 100) — less work than publishing, and
fine for a small testing group. Two real consequences to tell testers
up front: they'll see an "unverified app" warning (expected, click
through), and their Calendar-push refresh token expires after 7 days if
they go a week without signing in again (doesn't affect trip planning
itself, only Calendar export).

## 4.4 The `product-only` lightweight branch

A separate branch (`product-only-2026-09-10`) exists with every test
file, `requirements-dev.txt`, and every internal doc (`CLAUDE.md`,
`STATUS.md`, `decisions.md`, `progress.md`, `docs/`) removed — 202
tracked files down to 147. Built for a specific request ("as lightweight
as possible" for sharing raw source). **This is not the branch to
deploy from or build on** — it has no automated test gate and no
institutional memory, by design. `main` remains the real source of
truth; this branch is a point-in-time export, same spirit as this
document itself but for source code rather than documentation.

---

# Part 5 — Testing, CI/CD, and Security Posture

## 5.1 Testing

**Backend**: 33 pytest files under `backend/tests/` (excluded from this
document's file-by-file section — see the file list in `git ls-files`).
Uses an in-memory SQLite database and mocks every real Gemini call, so
the full suite runs with no live Postgres instance and no
`GEMINI_API_KEY`. Key fixtures (`conftest.py`): an `override_auth`
fixture stands in for real JWT verification everywhere (every test runs
as a fixed, auto-provisioned test user); autouse fixtures mock
`generate_conversation_title` and other LLM-calling functions by
default across the whole suite, with individual test files shadowing
those defaults where they specifically test that function's own
internals (pytest resolves the closest-scoped fixture first — a
same-named local fixture in one file overrides the global one just for
that file).

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest -v
```

**Frontend**: 8 Vitest + React Testing Library test files (introduced
2026-09-06, not every component has coverage yet), `jsdom` environment,
no dev server or backend needed.

```bash
cd frontend
npm install
npm run test
```

## 5.2 CI/CD (`.github/workflows/ci.yml`)

Three jobs, on every push to `main` and every PR:
1. **`lint-and-test`** (backend) — `ruff check .`, then `pytest -v`.
2. **`frontend-lint-and-build`** — `eslint`, `npm run test` (Vitest),
   `npm run build`.
3. **`build-and-push`** — only on an actual push to `main` (not PRs),
   after both jobs above pass. Builds and pushes both Docker images to
   GHCR (`ghcr.io/starkparsa/itinera-{backend,frontend}:latest`, both
   public). This job builds the images used by `docker-compose.share.yml`;
   it does not deploy anywhere.

## 5.3 Security posture

- **Row-level security** (Postgres, live 2026-09-08) — see §2.4 and
  §2.6's FK/cascade summary above for the exact policy shape.
  Verified against the real dev database with a two-user isolation
  script (cross-user read/write both correctly blocked).
- **Rate limiting**: two independent layers — `rate_limit.py`'s
  IP-keyed `slowapi` limiter (flood/abuse protection, in-memory,
  100/minute app-wide default, 10/minute on `POST /trips/generate`,
  5/minute on `POST /auth/login`) and `usage_quota.py`'s DB-backed,
  per-account daily cap (a real cost cap that survives horizontal
  scaling, distinct from flood protection — a shared IP or one account
  rotating IPs isn't bounded by the first layer alone).
- **Secrets encrypted at rest**: Google Calendar access/refresh tokens
  (`cryptography.fernet`, `TOKEN_ENCRYPTION_KEY`).
- **Passwords**: bcrypt, a common-weak-password blacklist, auth-event
  logging (never logs the password itself).
- **CORS**: an explicit `ALLOWED_ORIGINS` allow-list (fixed from a
  previous wide-open `["*"]`).
- **A four-part security pass** (2026-09-06) additionally covered: a
  frontend secrets audit and a full git-history secret scan (both
  clean, one real `.gitignore` gap found and fixed —
  `.env.local`/`.env.production` variants weren't covered), a
  Supabase-style anon-vs-service-role key check (not applicable — no
  Supabase, no client-side DB access exists anywhere in this app).

---

# Part 6 — Everything Else

## 6.1 Troubleshooting

**"502 Server Error: Bad Gateway" from `/trips/generate`** — the
backend reached out to Gemini (and Groq, if configured) and both
failed. Usually `GEMINI_API_KEY` missing/invalid, the free-tier quota
exhausted with no Groq fallback configured, or `GEMINI_MODEL` no longer
exists (Google retires model strings without much notice). Check the
backend logs for `RESOURCE_EXHAUSTED` specifically — that's a quota
problem, not a code/deploy problem. The error response's `detail` field
states the specific cause.

**Docker Compose hangs, or `docker ps` itself fails** — Docker Desktop
is most likely stuck mid-startup; restart it and retry before assuming
it's a project issue.

**Login fails with `invalid_client`/`redirect_uri_mismatch`** — the
OAuth redirect URI registered in Google Cloud Console doesn't match the
real frontend URL (this is the most common deploy-time misconfiguration
called out in both deployment guides).

**Every backend call 401s after a deploy** — `AUTH_BACKEND_SECRET`
doesn't match exactly between the frontend and backend's environment
variables. This is the single most common real misconfiguration in the
BFF auth flow (see §1.4).

## 6.2 Glossary — recurring project-specific terms

- **Trip Hub** — the `/trips/[tripId]` page: the persistent chat UI
  plus a collapsible right-hand panel showing Weather/Saved Places/
  Events for that specific trip.
- **`agent_context`** — the `Conversation.agent_context` column; a
  cached text blob of currency/place-context findings, gathered once
  per conversation and reused on every later turn rather than
  re-fetched.
- **The four intents** — `new_trip`, `edit_trip`, `question`,
  `off_topic`. The single classification every incoming message goes
  through before anything expensive happens.
- **Tour-guide mode** — a persistent conversational mode
  (`Conversation.tour_guide_mode`), activated by an explicit "be my
  tour guide"-style request, that changes the assistant's voice/
  persona on later question turns until the next planning turn clears
  it.
- **The named-place pool** — the deterministic, 8-category Google
  Places sweep (`gather_named_place_pool`) that gives itinerary
  generation real restaurant/bar/attraction names to use instead of
  generic descriptions.
- **BFF (backend-for-frontend)** — the auth pattern where Next.js owns
  the real OAuth session and mints short-lived JWTs for the backend,
  which never talks to Google directly. See §1.4.
- **`is_edit`** — the `Trip.is_edit` boolean distinguishing a
  conversational regeneration of an existing trip from a genuinely new
  one, so gamification stats aren't inflated by edits.
- **Fail open vs. fail safe** — a recurring pattern throughout this
  codebase: a non-critical fetch (weather, profile, agent context)
  "fails open" to an empty/null value rather than surfacing an error to
  the user, while a critical action (trip generation itself) surfaces a
  real error. Look for the phrase "fails open" or "fails safe" in code
  comments — it's a deliberate, named pattern here, not inconsistency.
