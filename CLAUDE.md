# CLAUDE.md — Itinera

This file is the project's north star. If a session's direction starts drifting
from what's below — scope creep, a re-litigated decision, a "shortcut" that
contradicts a principle here — stop and re-read this file before continuing.
If a request would meaningfully change scope, sequencing, or one of the
decisions below, ask the user before proceeding rather than assuming the
original plan still holds.

This file is a snapshot of current state and decisions, not a timeline —
for the session-by-session history (what changed, what broke, what was
learned building it), see [`docs/sessions/`](docs/sessions/README.md). Add
an entry there at the end of a session with real, shippable changes.

## What this product is

**Itinera** — a chat-driven AI travel planner. Describe a trip in plain language, get a
day-by-day itinerary, refine it conversationally, and eventually export it
(calendar file, live Google Calendar push). Full intended scope — not all of
this exists yet, see "Current state":

- End-to-end trip handling: itinerary planning, live/forecasted weather,
  flight prices, Google Maps for routing/POIs, hotel search, calendar export.
- A genuinely stateful assistant — real memory within a conversation (have
  it), and eventually cross-conversation trip-preference memory (later,
  separate feature — see roadmap, not to be pulled forward casually).
- Real user accounts with per-user chat history — added **last**, once the
  core product works (see decision log).
- Direct itinerary export for the user to keep/use elsewhere.

## Current state

Code is ground truth for "what exists" — this section is a snapshot, not a
substitute for reading the code. If they disagree, trust the code, but flag
the mismatch rather than silently editing one to match the other.

- **Backend**: FastAPI + SQLAlchemy. Chat-driven itinerary generation via
  chunked LLM calls (`llm_service.py`), an intent classification gate
  (`new_trip` / `edit_trip` / `question` / `off_topic`), a small agent
  tool-calling loop (`agent_service.py` + `tools.py`) and conversation-scoped
  agent-findings caching (`Conversation.agent_context`) —
  **paused again** (`agent_service.AGENT_TOOL_CALLING_ENABLED = False`) as
  of 2026-08-26, currency-only (this is the tool-calling *loop*, not
  weather). Weather (OpenWeather, the tool that used to live in this same
  loop) was removed outright on 2026-08-25 because it wasn't working
  reliably in practice, and stays removed *as a Gemini tool* — but real
  weather itself is back the same day via a completely different path:
  `weather_service.py`, a plain deterministic Open-Meteo client called
  directly by the routers on every trip, never routed through
  `agent_service.py`/Gemini at all (see decision log's Weather row). Don't
  conflate the two: the agent tool-calling loop is paused (currency only),
  weather is live and unrelated to that loop's on/off state. Currency
  conversion (Frankfurter) was re-enabled the same day the loop covers and
  verified live working correctly, but is paused again as of 2026-08-26 for
  a different reason — a product decision that it isn't needed, not a
  reliability problem (see decision log) — via the same kill switch flag,
  so `gather_trip_context()` short-circuits to `""` exactly as it did during
  its earlier pause. **A second, separate tool-calling loop exists as of
  2026-08-27**: `agent_service.answer_question_with_tools()` +
  `QA_TOOL_CALLING_ENABLED` (default `True`, independent of
  `AGENT_TOOL_CALLING_ENABLED`) expose a new `get_place_context` tool
  (`tools.py`, backed by the free, keyless `clients/wikipedia_client.py`) to
  conversational `question`-intent turns only — see decision log's Place
  context row for why this is a deliberately separate loop/flag/schema from
  currency's, not a shared one. **Persistent tour-guide mode added the same
  day** (`Conversation.tour_guide_mode`, migration `65524d890048`): once a
  message explicitly triggers it, later `question` turns keep the fuller
  narrative style by default until an `edit_trip`/`new_trip` turn clears it
  — see decision log's Persistent tour-guide mode row. **Two live bugs
  fixed the same day too**: itinerary day count silently drifting on a
  vague edit turn (now preserved via a soft prompt fact unless the request
  explicitly asks for a different length), and "be my tour guide"-style
  phrasing being misrouted to itinerary regeneration instead of the Q&A
  path (`INTENT_INSTRUCTIONS` now has concrete examples disambiguating the
  two) — see the "bug/correctness pass" item's Fourth round, below.
- **Frontend**: Next.js (App Router, TypeScript), `frontend/src/`. Migrated
  off Streamlit 2026-08-26 (see decision log). All four planned phases are
  now done: Phase A (UI parity, no auth), Phase B (Auth.js Google login +
  JWT bridge), Phase C (per-user data isolation), Phase D (Calendar push).
  The old two-button export UI (a `.ics` download button plus a separate
  "Connect Google Calendar" step) was merged into one always-shown
  **"Export Plan"** button (`CalendarPushButton.tsx`) the same day, once
  Calendar access got bundled into the base login — see decision log's
  Auth row for the full sequencing. Deliberately minimal — no trip-length
  field or similar form controls; trip parameters come from the prompt text
  (see decision log, this was a deliberate reversal, predates the Next.js
  migration and still applies). **Styled with Tailwind CSS v4 + shadcn/ui
  since 2026-08-29** (see decision log's UI styling row) — plain
  hand-written CSS (`globals.css`) is gone as the day-to-day styling
  mechanism; new UI should use Tailwind utility classes and, where a
  matching primitive exists, a `components/ui/*` shadcn component rather
  than a new bespoke class.
- **LLM**: Gemini API (`google-genai`), model `gemini-3.5-flash-lite` by
  default (`GEMINI_MODEL` env var, `llm_service.py`; `docker-compose.yml`'s
  inline fallback was still naming the pre-swap `gemini-3.6-flash` until the
  2026-08-26 cleanup pass caught and fixed the mismatch — harmless in
  practice as long as `GEMINI_MODEL` is set in `.env`, since that overrides
  either fallback, but worth knowing the two files can drift). Migrated
  off local Ollama/Mistral this session —
  native structured output (`response_schema`) replaced the hand-rolled
  markdown-fence JSON parser, native function calling
  (`types.FunctionDeclaration`) replaced the Ollama-specific tool loop in
  `agent_service.py`. `gemini-2.5-flash` (this file's original target) turned
  out to 404 for new API keys once actually tried — Google's own error
  redirects to `gemini-3.6-flash`; re-verify the current model string at
  `ai.google.dev/gemini-api/docs/models` if this starts 404ing again, model
  strings get retired without much notice.
- **Database**: **Postgres, hosted on Neon** — migration completed
  2026-08-29 (was MySQL; see decision log's "Database" row for the full
  story, including the two-divergent-datasets mess that prompted actually
  doing it). `backend/app/database.py` now requires `DATABASE_URL` to be
  set explicitly (fails fast with a clear error otherwise) instead of
  silently defaulting to a local MySQL URL that may not exist.
- **Auth**: real Google OAuth login (Phase B), real per-user data isolation
  (Phase C), and Google Calendar push (Phase D) — all shipped 2026-08-26,
  see decision log. Every trip/conversation endpoint requires a valid
  signed-in session and is scoped to the caller's own data;
  `POST /trips/{id}/push-to-calendar` pushes an itinerary as real events
  once a user has connected Calendar access — the Calendar scope is
  bundled into the base Google login itself as of the same-day Export Plan
  merge (see decision log's Auth row), not requested incrementally;
  `connectGoogleCalendarAction`'s incremental re-consent flow survives only
  as a fallback for a stale/revoked credential. Not usable end-to-end without a real
  Google OAuth client (`AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET`,
  `TOKEN_ENCRYPTION_KEY` in `.env`) — every phase verified as far as
  possible without one, up to Google's own `invalid_client` rejection of
  placeholder credentials, see decision log.

## Architecture: how a request actually flows

Everything (new trip, edit, follow-up question, off-topic message) goes
through the single `POST /trips/generate` handler in
[`routers/trips.py`](backend/app/routers/trips.py) — there's no separate
chat/message endpoint. Reading that file top to bottom is the fastest way
to understand the app; the branches below are its actual control flow, not
an aspirational design:

1. **Resolve the conversation.** Look up `conversation_id` if given,
   otherwise create a new `Conversation` (title = truncated prompt). Build
   `conversation_context` — a short summarized string of the last few turns
   (`_build_conversation_context`), used for classification/generation, as
   opposed to `_build_chat_messages`, which builds real role/content pairs
   for the Q&A path only.
2. **Classify** (`llm_service.classify_intent`) into `new_trip` / `edit_trip`
   / `question` / `off_topic` **before anything else runs** (principle #1).
   This one Gemini call is the fork point for everything downstream:
   - `off_topic` → a fixed, non-LLM decline string, message pair saved, done.
   - `question` → `llm_service.answer_question`, grounded in real chat
     history plus two independently-gathered context strings: the cached
     agent findings (`agent_service.gather_trip_context` — currently a
     no-op, always `""`, while `AGENT_TOOL_CALLING_ENABLED = False`, see
     decision log; when it was on, fetched fresh only if
     `conversation.agent_context is None`, i.e. once per conversation) and
     the conversation's latest `Trip`'s real forecast
     (`weather_service.get_or_refresh_trip_weather` +
     `summarize_for_prompt`, cache-checked on *every* question turn since
     it's a cheap TTL cache read, not a Gemini call). If that trip has no
     resolved `start_date` yet, `date_resolver.resolve_trip_start_date` is
     tried against the *question's own text* first (e.g. "this weekend")
     and persisted onto the trip if it resolves — added 2026-08-26 after a
     live bug where a question naming its own date still got "I don't have
     weather data" because only the generating prompt was ever checked (see
     decision log). This is the only row that mutates a `Trip` outside the
     `new_trip`/`edit_trip` branch; no `ItineraryItem` rows are touched.
   - `new_trip` / `edit_trip` → `llm_service.generate_itinerary`, which
     internally calls `_infer_trip_meta` (destination + day count) and then
     `_generate_chunk` once per `CHUNK_SIZE_DAYS`-day window (chunked
     generation, see "How long trips are generated" history in
     `docs/sessions/`), reusing `conversation.agent_context` if already set
     instead of re-running the agent loop on every edit. The route then
     resolves a real `start_date` via `date_resolver.resolve_trip_start_date`
     (falling back to the conversation's previous `Trip.start_date` on a
     turn with no date phrase), creates the `Trip` + `ItineraryItem` rows,
     fetches weather for it, and stores a rich itinerary summary
     (`_summarize_itinerary`) as the assistant's `Message` — not a one-liner
     — so later turns have real detail to reference.
3. Every branch ends by appending a `user` and `assistant` `Message` row to
   the conversation and committing — this is the entire mechanism behind
   "the assistant remembers the conversation": there's no separate memory
   store, just these rows re-read and re-summarized on the next turn.

**Data model** (`models.py`): `User 1—* Conversation 1—* Message`, and
`Conversation 1—* Trip 1—* ItineraryItem`. A `Message` optionally points at
the `Trip` it produced (`trip_id`). `Trip.conversation_id` is
`ON DELETE SET NULL`, not cascade — deleting a chat thread unlinks its
trips rather than deleting them (MySQL enforces the FK; SQLite in tests
doesn't, which is why this only ever surfaced against a real database).
`Conversation.agent_context`, `Trip.start_date`, and `Trip.weather_json`/
`weather_fetched_at` are the three pieces of cross-turn state everything
above reads and writes.

**Frontend** (Next.js, `frontend/src/`) is a thin client: it never calls
Gemini, Groq, Open-Meteo, or Frankfurter directly — every one of those
lives behind `BACKEND_URL`, called only from server-side code
(`lib/backend.ts`'s Server Actions, and the `.ics`-proxying Route Handler
at `app/api/trips/[tripId]/calendar/route.ts`), never from the browser. It
POSTs to `/trips/generate` and lists/loads history via
`routers/conversations.py`'s endpoints, keeping `activeConversationId` in
React state (`ChatApp.tsx`) — this predates auth (Phase A only, see
decision log); once Auth.js lands, `lib/backend.ts` is where the
backend-bound JWT gets attached to these same calls.

## Key decisions (with rationale — don't re-litigate without new information)

| Decision | Rationale |
|---|---|
| LLM: Mistral (local) → **Gemini** — **done** | Workable free tier for hobby scale, no card required. Gives native structured JSON output (`response_schema`) and native function calling, replacing the old hand-rolled markdown-fence JSON parser and Ollama-specific tool loop — confirmed delivered, not just aspirational (`_parse_json` is gone entirely). Concrete correction found only by actually trying it: `gemini-2.5-flash` (this row's original target) 404s for new API keys; migrated to `gemini-3.6-flash` instead, which is a reasoning model requiring `thinking_config.thinking_level=MINIMAL` to avoid burning the output-token budget on invisible thinking tokens, and whose function-response messages must use `role="user"` (`role="tool"` is rejected outright, despite that being Ollama's shape). Free-tier RPM/TPM/RPD numbers are no longer published in static docs (only live per-account in AI Studio) — re-verify via your own account before relying on a specific figure. **One concrete figure this account actually hit, 2026-08-25**: `gemini-3.6-flash`'s free tier is capped at **20 requests/day** per project (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, confirmed via a live 429 after a day of testing) — easy to exhaust during active development (each `/trips/generate` call alone is 2+ Gemini calls: meta-inference + at least one chunk), not just real usage. A `502 Bad Gateway` from `/trips/generate` most likely means this, not a code/deploy problem — check the backend container logs for `RESOURCE_EXHAUSTED` before assuming otherwise. **Model swapped again, same day, 2026-08-25 — `gemini-3.6-flash` → `gemini-3.5-flash-lite`**, specifically to escape the above 20/day wall: `gemini-3.5-flash-lite` is a distinct model in Google's quota system (confirmed live — it answered successfully while `gemini-3.6-flash`'s daily cap was still exhausted) and passed every mechanical check live: clean `response_schema`/`.parsed` output, correct `start_day`/`end_day` chunk-range instruction-following, correct `convert_currency` function-calling (calls when useful, doesn't over-call when a prompt has no budget). **Google's open-weight Gemma 4 (`gemma-4-31b-it`, `gemma-4-26b-a4b-it`, also servable via the same Gemini API/SDK) was tried first and rejected** after live testing found real problems: `response_schema` didn't stop it from appending a trailing `` ``` `` markdown fence after the JSON (broke `response.parsed` entirely — Gemma answered `None`, the raw text needed manual `model_validate_json` and even then failed on the trailing fence), and it didn't reliably follow the explicit "write ONLY days N through M" chunk instruction (returned 1 day when 3 were asked for). The 26B-A4B (MoE) variant was worse still — a real degenerate token-repetition loop on part of a generated itinerary ("...-alonnage-alonnage-alonnage..." repeated dozens of times), not usable for user-facing content. Gemma 4 remains a real, notable option (Apache 2.0, self-hostable later, native function calling) but not a drop-in replacement without real prompt-engineering work first — don't re-attempt it as a quick fix without addressing both issues found here. `gemini-2.5-flash-lite` (an earlier candidate) is confirmed 404ing for new users as of this change, redirecting to `gemini-3.5-flash-lite` — that's already what's in use. |
| Database: MySQL → **Postgres on Neon** — **done, 2026-08-29** | pgvector lives in the same DB instance for the later cross-trip preference-memory feature — no separate vector service to run or pay for. Neon has no idle-pause gotcha (unlike Supabase's free tier). Trade-off accepted knowingly: Neon doesn't bundle free Auth the way Supabase would have, so auth is a fully separate build. **Local dev MySQL clarified, 2026-08-29**: "wired and working" was true, but not the way this file implied — local dev MySQL is **Docker's** (`docker compose up -d mysql`, `docker-compose.yml`'s `mysql` service, host port **3307**, not 3306), not a native OS-level MySQL install. `.env`'s `DATABASE_URL` previously pointed at `localhost:3306` — which happened to also be a native Windows MySQL80 service running on this dev machine for unrelated reasons, with its own `travel_user` whose password doesn't match `.env`'s `travel_pass` at all. Two real, divergent local datasets were found from this confusion: the Docker container (3 users/5 conversations/20 trips/239 itinerary items, one migration behind head) and a `backend/_dev_site.db` **SQLite file that had been accidentally committed to git** (bundled into the unrelated `12fdcd6 "wiki updates"` commit — 2 users/3 conversations/6 trips, at the current migration head, likely from a session that had `DATABASE_URL` overridden to SQLite at some point without that override ever being persisted anywhere tracked). Per explicit user decision, **Docker MySQL's data was kept as the one true history** (larger, more established) and brought current via a plain `alembic upgrade head` (`f0fa120ecdf7 -> 65524d890048`, adding `tour_guide_mode`) — the SQLite file's more recent-but-smaller data was **not** merged in, to avoid silently colliding overlapping primary keys across two independently-numbered datasets. `.env` now points at `localhost:3307`; `backend/_dev_site.db` is untracked from git and `.gitignore`d (kept on disk, not deleted) so this can't happen again silently. If local dev MySQL breaks again, check `docker compose ps mysql` first — do not assume a native service is involved unless one is deliberately set up. **Migration itself executed the same day**, once this whole mess made "stable" the explicit ask: user created a Neon project (account creation isn't something Claude does — see the assistant's own action rules — so this one step was necessarily manual), then everything else was automated. Schema created via the existing `Base.metadata.create_all()` + `alembic stamp head` convention documented in `main.py`/`README.md` for a brand-new database — **a real bug was hit and fixed live doing this**: a first attempt imported `Base`/`engine` from `app.database` without also importing `app.models`, so `Base.metadata` was empty and `create_all()` silently created zero tables while still reporting "success" (the exact same class of bug CLAUDE.md already documents for `alembic/env.py`'s missing side-effect import — caught this time by explicitly querying `information_schema.tables` afterward rather than trusting the script's own printed confirmation). Data copied from Docker MySQL with a new one-off script, `backend/scripts/migrate_to_neon.py` (table-by-table in FK order, preserving primary keys, resetting Postgres's serial sequences afterward since explicit-PK inserts don't advance them) — verified row-for-row afterward (3 users, 5 conversations, 21 trips, 26 messages, 253 itinerary_items, 2 Calendar credentials; counts had grown since the earlier reconciliation entry above from real interim usage, not a discrepancy). `backend/app/database.py`'s `DATABASE_URL` env var is now required (raises a clear `RuntimeError` if unset) rather than defaulting to a local MySQL URL that may not exist — a silent wrong-default was exactly what caused the whole mess this row is about. `docker-compose.yml`'s `backend` service now passes `DATABASE_URL` straight through from `.env` instead of hardcoding a `mysql+pymysql://...@mysql:3306/...` string; the local `mysql` service definition itself is kept (behind a `legacy-mysql` Compose profile, not started by default) rather than deleted outright, in case it's wanted again. `backend/requirements.txt` gained `psycopg2-binary`; `pymysql` stays for now (the migration script's source-side reader) — remove once Docker MySQL is actually decommissioned. See [`docs/sessions/2026-08-29-neon-postgres-migration.md`](docs/sessions/2026-08-29-neon-postgres-migration.md). |
| Auth: built **last** — now actively **starting**, 2026-08-26 | Schema already supports it (`user_id` everywhere). When it happens: **Google OAuth** specifically — Calendar's MCP server needs a Google Cloud project + OAuth consent anyway (see Calendar row), so the login flow should cover identity + Calendar scope together. Maps MCP now also needs the same Google Cloud project for billing (see Maps row), though its exact auth mechanism (OAuth vs. a plain API key) isn't confirmed yet — if it turns out to be API-key-only, Maps doesn't need to be bundled into the user-facing OAuth flow itself, just the shared Cloud project/billing setup. Confirm before finalizing the OAuth build-order step. **Architecture decided, Phase A shipped, 2026-08-26**: real per-user accounts required migrating off Streamlit first — Streamlit has no HTTP routing layer of its own, so it can't host an OAuth callback route or read browser cookies, both required for a real login. Chosen architecture is a BFF (backend-for-frontend) pattern: **Next.js + Auth.js (NextAuth)** is the OAuth client and session owner (Google provider, JWT session strategy — not database sessions, to avoid a second ORM/schema in Node land alongside the existing Python/SQLAlchemy models), and FastAPI becomes a stateless resource server that verifies a short-lived, backend-scoped JWT (HS256, a secret shared between the two services — not JWKS/RS256, since this is two services under one team's control, not a public API with unknown consumers) minted server-side by Next.js on every backend call; the JWT's `sub` claim maps to a new `User.google_sub` column (not `email`, which isn't guaranteed stable). Sequenced as four phases, each independently demoable: **A (done, 2026-08-26)** — full Next.js UI parity with the old Streamlit app (chat, sidebar, itinerary/weather rendering, both `.ics` export buttons, same start_date-gating rule), against the *unmodified* backend, no auth at all yet, validating the rewrite independently of auth risk; **B (done, 2026-08-26)** — Auth.js Google login (`frontend/src/auth.ts`, `/login` page, Google provider, JWT session strategy), the JWT bridge (`frontend/src/lib/authHeader.ts` mints a short-lived HS256 token from the session; `backend/app/auth.py::get_current_user` verifies it and auto-provisions a `User` on first sight of a new `google_sub`), `User.google_sub` (Alembic now set up in `backend/alembic/`, migration `5f96d91ad93a`; `main.py`'s `create_all()` stays for fresh SQLite/MySQL installs — see its comment for the `alembic stamp head` vs. `upgrade head` distinction on a brand-new DB), and `generate_trip` deriving `user.id` from the verified token instead of the old client-trusted `request.user_id` (that field stays in `schemas.TripRequest` for now, unused, formal removal is Phase C). Verified live end-to-end up to the point only real Google credentials unlock: unauthenticated `/` correctly redirects to `/login`, clicking through actually reaches `accounts.google.com`'s real OAuth consent endpoint with a correctly-formed authorize URL (confirmed via its own `invalid_client` error against the placeholder credentials used for this verification), `/api/auth/session` responds correctly, and `POST /trips/generate` now correctly 401s with no bearer token. Real `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` (a real Google Cloud OAuth client — needs a human with a Google account, can't be done from here) are the only remaining thing needed to complete a real login. **C (done, 2026-08-26)** — retrofit real ownership checks on every endpoint that had none: `get_trip`, `export_trip_calendar`, `get_conversation`, `delete_conversation` all gained `Depends(get_current_user)` + a `user_id == user.id` filter (404, not 403, on a cross-user id — never confirms the id exists to someone who doesn't own it); `list_conversations`'s client-supplied `user_id` query param (`DEFAULT_USER_ID = 1`, exactly as untrustworthy as the old `TripRequest.user_id`) was removed the same way. `TripRequest.user_id` is gone from `schemas.py` entirely now, not just unused. New `backend/tests/test_ownership_isolation.py` (6 tests) proves cross-user isolation for all five endpoints by swapping FastAPI's `get_current_user` override mid-test to simulate two different logged-in users — including a regression guard that a client-supplied `user_id` in the request body has zero effect, confirming the removal actually stuck rather than silently regressing. Verified live: every one of the five endpoints now correctly 401s with no bearer token at all (confirmed via curl against the running Docker stack), and the full 159-test suite passes. **D (done, 2026-08-26)** — **go/no-go check ran, and it said no**: live search confirmed `google-genai`'s MCP support is still explicitly labeled experimental (Google's own SDK docs), and the Calendar MCP server itself is gated behind Google's Workspace Developer Preview Program, not GA — neither is a base to build on. Used the named fallback, `googleapiclient`, directly against Calendar API v3 instead — which is also the architecturally correct call independent of the experimental status: pushing an itinerary to a calendar is a deterministic user click, never a judgment call for Gemini to make (same reasoning that already kept weather out of the LLM tool-calling loop). New `backend/app/google_calendar.py`: encrypts tokens at rest (`cryptography.fernet`, new `TOKEN_ENCRYPTION_KEY`), refreshes an expired access token automatically and persists the refresh, reuses `calendar_export.resolve_event_time` (renamed from `_event_start_time`, now public specifically for this reuse) so the `.ics` export and the live Calendar push never disagree about what time an event lands at. New `GoogleCalendarCredential` table (Alembic migration `f0fa120ecdf7`) and `POST /trips/{id}/push-to-calendar` (`428` when not connected, `502` on a real Calendar API failure, same ownership check as every other trip endpoint). Incremental OAuth consent: the base Google login never requests the Calendar scope (`access_type`/`prompt` overrides live only on the one-off `signIn` call from "Connect Google Calendar", not the provider config) — most users who only ever use the already-working `.ics` export never see a broader consent screen than they need. New `POST /auth/google-calendar-token` (Next.js's Auth.js `jwt` callback calls this server-side, right after Google grants the scope, to persist the tokens — they never reach the browser) and `GET /auth/google-calendar-status` (lets the UI show "Connect" vs. "Push" without guessing from a failed attempt). 16 new backend tests (encryption round-trip, credential upsert/refresh-token-preservation, token refresh, all the router status codes) — full suite (175 tests) passes, lint clean, full Docker stack rebuilt and confirmed running. **A real, unrelated bug was found and fixed while building this**: `backend/alembic/env.py`'s `from app import models` import (needed only for its side effect of registering every table on `Base.metadata`) had been silently deleted by an earlier `ruff --fix` run that (correctly, by its own rules) flagged it as unused — this made `target_metadata` empty, and a first attempt at this phase's migration autogenerated a script that would have **dropped every existing table**. Caught before applying by reading the generated migration rather than trusting `--autogenerate` blindly; fixed with a `# noqa: F401` and a comment explaining the import is for its side effect, not its name. Worth remembering: always read what `alembic revision --autogenerate` actually produced before running `upgrade head` against a real database, especially after any lint auto-fix touched `alembic/env.py`. **Same day, follow-up after real credentials worked**: merged into one **"Export Plan"** button (`CalendarPushButton.tsx`) — `ExportButton.tsx`/`.ics` UI deleted (the backend endpoint stays, just unlinked from the UI), and the Calendar scope moved from the incremental `connectGoogleCalendarAction` override onto the *base* Google provider config in `auth.ts` (`access_type: "offline"`, deliberately no `prompt: "consent"` there — a genuinely first login still shows real consent naturally). One consent screen at login now covers Calendar too; `connectGoogleCalendarAction` demotes to a recovery-only fallback for a stale credential (flagged: this project's OAuth consent screen is presumably still "Testing" status, which caps refresh tokens at 7 days — expected to eventually trigger that fallback, not a bug when it does; fixing it for good means publishing to Production in Google Cloud Console, a manual step, not built for speculatively). Verified live: the real first-login redirect's `scope=` query param now includes `calendar.events` alongside the base scopes. **Real bug found in first live click-through, same day**: clicking "Export Plan" for real failed with `Google Calendar API error: Missing time zone definition for start time` — Google's REST Calendar API, unlike an `.ics` file, rejects a timed (`dateTime`) event with no timezone at all; `calendar_export.py`'s deliberate floating-time design (valid RFC 5545, no `TZID`) doesn't carry over to the live API the way it was assumed to. Fixed by adding `weather_service.geocode_timezone()` (Open-Meteo's geocoding search response already includes a `"timezone"` field per result, confirmed live via a direct API call — zero extra network cost beyond the existing geocode lookup) and setting `timeZone` on every timed event's `start`/`end` in `google_calendar.py`; all-day (`date`) events are untouched, `timeZone` doesn't apply to them. Falls back to `"UTC"` only if geocoding itself fails — a neutral default, not a fabricated specific zone. 5 new tests (2 geocode_timezone unit tests, timezone-inclusion-on-timed-events, no-timezone-on-all-day, UTC fallback) — full suite (180 tests) passes. |
| Place context: Google Maps integration researched, **deferred**; **Wikipedia-only tool shipped instead**, 2026-08-27 | User asked for a Maps integration (distance, directions, place metadata/history, transportation tips, LLM-driven). Full research done and a build plan drafted: Google Maps Platform has **no genuinely cardless free path** for Places API (New)/Routes API/Geocoding API — a billing account with a valid payment method is required just to get past 1 request/day, even though usage would likely stay within the free monthly thresholds (10,000/mo Essentials, 5,000/mo Pro, 1,000/mo Enterprise) at this app's scale; the user chose to add a Google Cloud billing card for a future pass rather than the free/no-card OSM-based alternative (Nominatim + OpenRouteService + Overpass + Wikipedia/Wikivoyage, also fully researched). Google's own "Maps Grounding Lite" MCP server was evaluated and rejected for that future work too — narrower than needed (DRIVE/WALK routing only, no transit, no rich Place Details) and `google-genai`'s native remote-MCP support is still experimental. **That full Maps design was not committed to any file** (only this session's conversation and `docs/sessions/2026-08-27-wikipedia-place-context-tool.md`'s "Open items" note) — re-derive it from scratch (or ask for the prior research) rather than assuming it's preserved somewhere, if that work resumes. **Scoped down instead, same session**: shipped a Wikipedia-only `get_place_context` tool (`tools.py`, `clients/wikipedia_client.py`) needing no billing account at all — brief (~320 char, default) or detailed (capped 2000 char) place overview, resolved via Wikipedia's opensearch/summary/full-extract endpoints. Reached through a **new, separate** tool-calling loop (`agent_service.answer_question_with_tools()` + `QA_TOOL_CALLING_ENABLED`, default `True`) rather than folding into the existing currency loop — a real correctness reason, not just tidiness: `gather_trip_context`'s caller caches its result once per conversation forever (right for currency, one fact per trip; wrong here, since a different place can be asked about every turn), and each loop is given only its own tool's schema (`tools.CURRENCY_TOOL_SCHEMAS`/`tools.QA_TOOL_SCHEMAS`, never the combined `tools.TOOL_SCHEMAS`) so flipping one loop's flag can never make the other loop's tool reachable as a side effect. Verified live (real Gemini + Wikipedia calls): brief vs. detailed genuinely differ, and asking about a second place in the same conversation correctly gets a fresh answer, not the first place's cached one. One live-verification finding fixed the same session: the model's own reply padded a "brief" tool result with extra pretrained-knowledge facts, undermining the brevity requirement — fixed with an explicit system-prompt instruction to match reply length to the detail level used, not the model's own general knowledge. Q&A-only for this phase, not wired into itinerary generation (`ItineraryItem` has no location field to resolve against). **Extended to itinerary generation itself, 2026-08-29**: a third, fully isolated tool-calling loop, `agent_service.gather_place_context_for_itinerary()` + `PLANNING_TOOL_CALLING_ENABLED` (default `True`) + `tools.PLANNING_TOOL_SCHEMAS`, runs concurrently with the existing currency loop and `_infer_trip_meta` inside `generate_itinerary()`'s once-per-conversation gather step. Both place-context loops call the identical `get_place_context` tool underneath; kept as separate loops/flags (not folded into the existing Q&A loop or the currency loop) for the same reason currency and Q&A were already separate — different caching semantics (this one's result gets cached forever in `Conversation.agent_context`, same slot currency already used; Q&A's never gets cached) and per-feature kill-switch isolation. No new DB column — reuses the existing `agent_context` cache slot and join pattern (`" ".join(currency, place_context)` for whichever are non-empty). Per-item/per-day place lookups *during* chunk generation itself remain out of scope (chunk generation's `response_schema` structured-output calls don't mix cleanly with live function-calling in the same call, and `ItineraryItem` still has no location field) — this is one background-grounding pass before generation starts, not a lookup per itinerary item. Same session, `tools._DETAILED_CHAR_CAP` (tour-guide-mode depth) raised `2000 -> 6000` — explicit product decision to raise, not remove, the cap; live-verified a 2478-char Eiffel Tower extract that would have been truncated at 2000 now comes through whole. **Live-verification finding, same session**: the new itinerary-planning loop is reliable when called in isolation but returned silently empty in roughly half of a handful of end-to-end trial runs when run as the 3rd simultaneous Gemini call inside `generate_itinerary()`'s concurrent gather step — consistent with this account's already-documented free-tier rate-limit sensitivity (see the Reliability/Groq row below), not a new bug; `_infer_trip_meta` itself was observed falling back to its pre-existing `destination="Unknown"` path under the same concurrent load in one of those runs. Accepted as-is per this module's existing "fails quietly, generation proceeds anyway" contract (identical to how the currency loop has always been allowed to fail) — not patched with retries or reduced concurrency this session; see [`docs/sessions/2026-08-29-wikipedia-context-for-itinerary-planning.md`](docs/sessions/2026-08-29-wikipedia-context-for-itinerary-planning.md) for the full live-verification trace. **The earlier deferred Google Places integration was un-deferred, 2026-09-01**, on a live, user-supplied, billing-enabled API key (verified live before writing any code — a real `places:searchText` call returned real data) — scoped deliberately narrower than the full Maps design this row deferred above: place info + nearby search only, no routing/directions, so the Maps/routing build-order item (item 4) and its Maps-MCP plan stay untouched. Two new tools, `get_place_details` and `find_nearby_places` (`clients/google_places_client.py`, wired into `tools.py`), added to the *same* two loops `get_place_context` already reaches (QA and itinerary-planning) rather than a new loop — no new kill-switch flag either; `GOOGLE_PLACES_API_KEY`'s presence (`google_places_client.PLACES_API_ENABLED`) is itself the kill switch, unset it and both new tools return `{"error": ...}` immediately with zero behavior change to the existing Wikipedia tool, mirroring `GROQ_API_KEY`'s existing optional-key convention. Wikipedia and Places deliberately do **not** overlap in responsibility: Wikipedia stays the free source for history/cultural-significance questions, Places (billed, so used more sparingly per explicit system-prompt cost-awareness guidance) covers current/practical facts (rating, price level, open-now status) and real nearby-place recommendations — a capability Wikipedia has no equivalent of. Live-verified the model correctly discriminates between all three tools by question type in the same conversation flow (a rating/hours question called `get_place_details`, a pure-history question stayed on `get_place_context`, a recommendation question called `find_nearby_places`). **A real bug was found and fixed live doing this**: `find_nearby_places` originally resolved its `near` argument only via `weather_service.geocode` (Open-Meteo, city-name-oriented) — a landmark-level `near` ("Louvre Museum, Paris") reliably failed geocoding, and the model's own retries with progressively broader phrasings burned through all of `MAX_TOOL_ROUNDS` before the one phrasing that worked ("Paris" alone, on the last allowed round) ever got a chance to be summarized into a final answer — the tool itself worked, the shared round budget didn't survive the model's guessing. Fixed with a fallback in `tools._geocode_for_places`: try the free Open-Meteo geocoder first, fall back to Google Places' own `text_search` (which resolves landmark-level names directly) only when that fails — resolved deterministically in one function call instead of leaving it to repeated LLM guesses, the same discipline principle #6 already applies to date arithmetic. Re-verified live after the fix. See [`docs/sessions/2026-09-01-google-places-integration.md`](docs/sessions/2026-09-01-google-places-integration.md). |
| Persistent tour-guide mode, 2026-08-27 | Previously, whether a Q&A reply was "brief" or "tour-guide-detailed" was decided fresh, independently, every turn by the model, based only on that turn's own wording — so a follow-up that didn't repeat "be my tour guide" reverted to brief. Fixed with real conversation-scoped state: new `Conversation.tour_guide_mode` (Boolean, migration `65524d890048`) stays `True` across later question turns until an `edit_trip`/`new_trip`-classified turn (i.e. the user explicitly talks about planning again) turns it back off — unconditionally, regardless of what the triggering signal says, so there's no ambiguous state. Trigger detection reuses the *existing* `classify_intent` Gemini call rather than a separate LLM call or a keyword list: `IntentResult` gained `tour_guide_requested: bool`, extracted from the same response. `agent_service.answer_question_with_tools` gained a `tour_guide_mode` parameter that folds a persistent-mode note into the system prompt — distinct from `QA_TOOL_SYSTEM_PROMPT`'s existing per-turn "be my tour guide" instruction (which only covers the triggering turn itself), and explicitly drives the tool's actual `detail="detailed"` argument on later turns, not just reply tone, to avoid starving the model of real material to expand from (the exact fabrication risk already fixed earlier the same day). Mechanical but wide-blast-radius test fallout: `classify_intent`'s return type changed from `str` to `tuple[str, bool]`, requiring every one of 28 mock call sites across 4 test files (not just the router tests) to update — found only by grepping the whole test tree directly, not trusting a narrower design-pass search. Live-verified all 5 scenarios (trigger, persistence across a vague follow-up, turn-off on replanning, brief-by-default afterward, and an adversarial combined-signal message) against the real Gemini API — see `docs/sessions/2026-08-27-persistent-tour-guide-mode.md`. **No UI indicator for now, by explicit product decision — silent backend behavior only** (superseded 2026-08-29, see below). **Revised, 2026-08-29, per user feedback on three points**: (1) the activating turn now prepends a fixed `"Tour guide mode on. "` string to the reply — added **deterministically in Python** (`routers/trips.py`, keyed off a new `activating_tour_guide` local: `tour_guide_requested and not conversation.tour_guide_mode`, captured before the mutation), not as an LLM-phrased instruction, for the same reason principle #6 keeps date arithmetic out of the model's hands — exact required wording is more reliable coming from code than from trusting the model to say it verbatim every time. Said once, on activation only; later turns don't repeat it (a user-clarified choice over gating every reply behind it). (2) **The "detail=detailed forced on every later turn" part of the design above is reversed** — `answer_question_with_tools`'s `tour_guide_mode` branch in `agent_service.py` no longer forces `detail="detailed"`; every turn (guide mode or not) now defaults to `detail="brief"` plus a request for a touch of relevant history, escalating only when *that specific message's own wording* explicitly asks to go deeper ("go deeper", "tell me more", "the full history") — and deliberately not sticky (an earlier "go deeper" doesn't carry into the next unrelated question). Safe to revert now specifically because the fabrication risk that motivated forcing `detailed` in the first place was later fixed a different, more targeted way (`QA_TOOL_SYSTEM_PROMPT`'s own anti-invention instruction, see the "bug/correctness pass" item's Fourth-round same-day follow-up) — forcing detail was never the only thing keeping that in check. (3) **The "no UI indicator" decision is reversed too** — `tour_guide_mode` is now exposed on `schemas.ConversationDetail` (not `TripResponse`: a question-turn's assistant `Message` has no `trip_id` at all, so a trip-level field would never reach the frontend for the turns that matter) and read by `ChatApp.tsx` into new `tourGuideMode` state, which sets `data-tour-guide-mode="true"` on the app's root wrapper. `globals.css` overrides `--primary`/`--ring`/`--sidebar-primary`/`--sidebar-ring` under that attribute selector to an amber accent (Tailwind's amber-700/400 oklch stops, light/dark — same tuned-not-hand-picked sourcing as the teal base palette) — every component already themed off those tokens (buttons, active sidebar item, user bubble, default badges) picks it up with zero per-component changes, and it reverts to teal automatically the next time a load reflects the flag going back off (no extra revert logic needed — `loadConversation`/`startNewChat` already set this state from whatever the backend last reported). No new frontend dependency. Live-verified all of the above against the real Gemini API via a scratch SQLite-backed backend instance (the shared dev MySQL instance was separately found to be rejecting its configured credentials at the time — flagged to the user as an unrelated environment issue, not fixed here) and a scratch mock-data preview route for the color swap, both deleted before finishing; see `docs/sessions/2026-08-29-tour-guide-mode-refinements.md`. **Real bug found live, fixed same day, follow-up**: a bare "be my tour guide" with no place named (the activation turn itself) triggered a full day-by-day recap of the entire already-generated itinerary instead of a short welcome — root cause was `QA_TOOL_SYSTEM_PROMPT` listing "be my tour guide" itself as one of the phrases that triggers `detail="detailed"`, alongside genuine escalation phrases like "tell me the full history"; the model treated *activating the persona* as a request to dump everything it knew about the trip. Fixed by dropping "be my tour guide" from that trigger list (the phrase now only affects persona/voice per the design above, not detail level) and adding an explicit instruction: when a message asks for the tour-guide persona without naming a specific place, give a short, friendly welcome (invite the user to pick a stop) rather than narrating every day already in the conversation. Live-verified against the exact reported scenario (a real 5-day Miami itinerary, then a bare "be my tour guide"): reply dropped from a full multi-paragraph day-by-day recap to a 284-character welcome ending in a question, and a same-conversation follow-up naming a specific place ("Tell me about South Beach") still got a real, grounded, brief answer afterward — confirming the fix didn't over-correct into refusing to answer real place questions. |
| Trip length: inferred from the prompt, no UI field | Explicitly rejected a "Trip length" slider/number-input in the Streamlit sidebar — say it in the message instead (e.g. "a week in Lisbon"). Don't re-add a form control for this without asking; it was tried and deliberately removed. |
| Weather (OpenWeather): **removed**; agent tool-calling step **re-enabled**, currency only | Weather wasn't working reliably in practice for real answers even after the fabrication/on-demand-fetch fix (root cause not fully diagnosed — the API key was present and valid-looking, so this wasn't simply a missing-key issue) and stays removed; re-diagnose from scratch (or reconsider the source — e.g. Open-Meteo, no key required, remains the pick regardless of the Maps-stack decision) before ever re-adding it. Currency conversion was paused alongside weather at the time rather than leaving a half-working step running, but has now been flipped back on (`agent_service.AGENT_TOOL_CALLING_ENABLED = True`, 2026-08-25) and verified live: a real Frankfurter call (500 USD → 60,624 ISK) was correctly picked up by the model, folded into a grounded summary with matching numbers, and — separately — a no-budget prompt correctly triggered no tool call at all rather than inventing one. `AGENT_TOOL_CALLING_ENABLED` stays as a kill switch if currency ever shows the same unreliability weather did. **Paused again, 2026-08-26 — for a different reason than weather's removal.** Currency was working correctly (the 2026-08-25 verification above stands); it's turned off now purely because of a product decision that currency conversion isn't needed, not a reliability finding. Same kill switch flag, flipped the other way (`AGENT_TOOL_CALLING_ENABLED = False`) — `gather_trip_context()` short-circuits to `""` again, no other code touched. A follow-up audit for the bug below's divergence pattern (generation-only logic missing from the Q&A path) also flagged that this tool-calling step's `Conversation.agent_context` gate caches "found nothing" per-conversation forever, so a later question that plainly needs a fresh currency figure would never get one — now moot with currency paused, but worth remembering if it's ever re-enabled. **Resolved, 2026-08-25 — weather is back, real-time, per-day, via Open-Meteo, and it's neither an MCP server nor a Gemini tool at all.** Evaluated community Open-Meteo MCP servers vs. building one ourselves vs. a plain `tools.py`-shaped function (per principle #8's decision rules) — landed on a fourth option once it became clear weather-to-*display* is never a judgment call the model makes (unlike currency, which the model opts into). It's a plain deterministic backend service (`date_resolver.py` + `weather_service.py`), called directly by `routers/trips.py`/`routers/conversations.py` on every trip, not registered in `tools.py`'s `TOOL_SCHEMAS`/routed through `agent_service.py` at all — so MCP's reason for existing (giving an LLM discoverable, callable tools) doesn't apply here, and the feature's marginal LLM cost is zero (no extra Gemini call, no extra tokens). Needed a new prerequisite that didn't exist at all: `Trip.start_date`, resolved from the prompt in real Python (`date_resolver.py`, regex-extracted date substrings + `dateutil`, never a whole-prompt fuzzy parse — that was tried first and confirmed live to misfire, e.g. "September 3rd" inside "...starting September 3rd" got polluted by an unrelated "5" elsewhere in the prompt into 2003-09-05) per principle #6. Verified live: real geocoding + a real Reykjavik forecast (7–11°C, overcast/light drizzle) came back correctly for a resolved date. Cached per-trip (`Trip.weather_json`/`weather_fetched_at`, 3-hour TTL) to stay well inside Open-Meteo's free 10,000/day cap regardless of how many times a trip is reloaded. **Fahrenheit added, 2026-08-25**: `weather_service._celsius_to_fahrenheit` computes both units with real Python arithmetic at fetch time (never left for the LLM to convert, same discipline as principle #6) — `DayWeatherOut` carries `temp_min_f`/`temp_max_f` alongside the existing Celsius fields, and the Streamlit display shows both ("High 11°C / 52°F"). **Threaded into conversational Q&A too, 2026-08-25** (see the bug/correctness-pass entry below for why): `routers/trips.py`'s question branch now looks up the conversation's latest trip's real forecast on every question turn and folds it into `answer_question`'s grounding via `weather_service.summarize_for_prompt` — `answer_question`'s system prompt was updated to allow stating the real Celsius/Fahrenheit figures exactly as given (not to invent a conversion when only one unit was provided, which is a different thing). **Known open gap, found in the same 2026-08-26 audit**: weather always geocodes `trip.destination`, never a different city named in a follow-up question ("what's the weather in Reykjavik this weekend?" against an Austin trip still answers for Austin) — left open, since unlike the date-resolution bug above there's no existing deterministic extractor to reuse; closing it needs either a new lightweight extractor or a fresh LLM call. |
| Flights: no live pricing API for MVP | No workable free flight-pricing API exists as of Aug 2026 — Amadeus self-service, the obvious free option, was fully decommissioned July 17 2026. Treat flight cost as an LLM-reasoned rough estimate, clearly labeled as such, until there's budget for a paid API (~$10-20/mo — Duffel, AeroDataBox) or a better free option surfaces. Re-check the landscape before building against a live flights integration. |
| Hotels: search/compare only, not booking | Real reservations need PCI-compliant payment flows and hotel partner agreements — out of scope for a free-tier indie MVP. Deep-link out to Booking.com/Google Hotels rather than booking in-app. |
| Maps: OSM-based stack → **reversed, Aug 2026 — switching to Google's official Maps MCP server** | Originally picked to avoid a Google Cloud billing account (Maps Platform needs one even at $0 spend). Reversed after Google shipped a fully-managed, officially supported Maps MCP server in 2026 (same wave as the Calendar MCP server below) that per Google's announcement bundles weather-forecast grounding alongside places/routing — potentially covering both the weather and Maps items on the future-tools list with one integration. Knowingly re-accepts the billing-account requirement the OSM pivot existed to avoid; judged worth it for an officially maintained server instead of hand-rolling and maintaining a 5-service OSM client (Nominatim/Overpass/OpenRouteService/Open-Meteo/Wikipedia) with its own reliability caveats (Nominatim's 1 req/sec cap, Overpass's no-SLA). **Unverified as of this decision** — Google's announcement didn't disclose Maps MCP pricing, free-tier limits, or exact auth flow (OAuth vs. API key); confirm all three before writing any code against it. The previously-drafted OSM-based Maps/routing plan (deep per-item coordinates + legs, energy/pacing signal, grounded importance notes) is superseded — re-derive the design against Maps MCP's actual tool surface once the above is confirmed, don't assume the old design transfers as-is. |
| Calendar: hand-rolled `googleapiclient` calls → **Google's official Calendar MCP server** (`calendarmcp.googleapis.com`) → **reversed back to `googleapiclient`, 2026-08-26** | Google shipped a fully-managed, officially supported remote Calendar MCP server in 2026 (OAuth 2.0, 8 tools: list calendars, retrieve events, check availability, create/update/delete events) — same prerequisite this project already needed anyway (a Google Cloud project + OAuth consent screen for the planned Google login), so adopting it costs nothing extra in setup and replaces what would've been hand-written `googleapiclient` calls with a maintained server. Still bundled with Google OAuth login exactly as originally planned (build order item 5) — unchanged by this decision, just the Calendar half is now MCP instead of a direct API client. **Reversed at Phase D implementation time**: the go/no-go check this row's own principle-#8 caveat called for came back negative — `google-genai`'s MCP support is still explicitly "experimental" (live-verified via Google's own SDK docs, not assumed), and the Calendar MCP server itself is gated behind Google's Workspace Developer Preview Program, not GA. Went with the originally-superseded `googleapiclient` approach instead (see the Auth decision row's Phase D entry for the implementation) — also the better architectural fit on independent merits: a Calendar push is a deterministic user click, not a Gemini judgment call, so MCP's "give an LLM discoverable tools" rationale never actually applied here the way it does for a real agent-facing integration. |
| Reliability: **Groq added as an automatic fallback** when Gemini's quota is exhausted, 2026-08-25 | Direct response to the `gemini-3.6-flash` 20-requests/day wall above — a live demo can't be allowed to 502 mid-presentation. Groq's free tier (30 RPM / 6,000 TPM / **14,400 requests/day**, no card, no expiry) is ~700x that cap. Scoped to `llm_service.py`'s core paths only (`_call_gemini`/`_call_gemini_chat`, so every caller — intent classification, meta inference, chunk generation, Q&A — gets it automatically) and gated strictly on `_is_rate_limited` (HTTP 429 specifically) so a real bug (bad schema, invalid key, Google's servers down) still fails exactly as before rather than being masked by "well, Groq answered." Deliberately **not** wired into `agent_service.py`'s currency tool-calling step — that already degrades gracefully to `""` on any failure, so it's lower-stakes and out of scope. New `groq_service.py`, using the `openai` SDK pointed at Groq's OpenAI-compatible endpoint (principle #3: reuse an existing wrapper, don't hand-roll one) — model is `llama-3.3-70b-versatile`, deliberately **not Gemma 4** despite Gemma also being servable via Groq (see the row above: real problems found live). Anthropic Claude and OpenAI were evaluated and ruled out for this — neither has a persistent free API tier in 2026 (both give a one-time ~$5 trial credit, then pay-as-you-go), which doesn't sustain this project's $0 budget; revisit if that constraint ever changes. Groq's structured-output strict mode requires every schema property to be listed as required, which doesn't match this app's schemas (e.g. optional `notes` fields) — used in best-effort (`strict: false`) mode plus manual `model_validate_json` instead of fighting that mismatch. Not yet live-verified end-to-end (no `GROQ_API_KEY` was available to test with this session) — verified via mocked tests only; live-verify before relying on this for an actual presentation. |
| Codebase cleanup pass, 2026-08-26 | Full read-through of every file under `backend/app/`, `backend/tests/`, and `frontend/src/` after the OAuth work above — not just `ruff`/`eslint`, which only catch dead code *within* a file, not a whole function/route with zero callers anywhere, and (as this pass found) neither one checks whether a file is in version control at all. **Most significant finding, a real bug, not a style issue**: `frontend/src/lib/` — `authActions.ts`, `authHeader.ts`, `backend.ts`, `mintBackendJwt.ts`, `types.ts`, `weatherIcon.ts` (the Server Actions that call FastAPI, the entire JWT-minting/auth-bridge logic, shared types) — had **never been committed to git, since the initial commit**, confirmed via `git log --all` returning zero commits for any of them. Root cause: the root `.gitignore`'s generic Python-packaging boilerplate has a bare `lib/` line meant for a Python build's output directory; unanchored gitignore patterns match at any depth, so it was also silently swallowing `frontend/src/lib/`. Every "full suite passes"/"Docker rebuilt and confirmed running" verification earlier this session was against this local disk, which still had the real files on it regardless of git — none of that would have caught this; only an actual fresh clone or a real CI checkout from `origin` would (and per this repo's own `ci.yml`, likely has been failing the `frontend-lint-and-build`/`build-and-push` jobs since Phase A, since GitHub Actions checks out from the remote, not this disk). Fixed by anchoring the pattern to the repo root (`/lib/`, `/lib64/`) and `git add`-ing all six files for the first time; scanned every other tracked directory for the same shadowing pattern and found no other collisions. Confirm the next real push actually shows these files landing in the GitHub repo, and check whether past CI runs on `main` were in fact red because of this. Found and removed one genuinely dead export: `frontend/src/lib/backend.ts`'s `getGoogleCalendarStatus()`, a leftover Server Action from before the same-day "Export Plan" button merge, with zero callers anywhere in the app (confirmed via repo-wide grep). Also found `backend/` had **no `.dockerignore` at all** — `docker build ./backend`'s context included the full local `.venv` (261MB, confirmed via `du`), even though nothing in it is ever `COPY`'d into the image; added one, verified the build context dropped to 772 bytes and the image still builds and runs identically. Split `pytest`/`httpx` out of `requirements.txt` into a new `requirements-dev.txt` — the production backend image was installing a test runner and test-only HTTP client for no runtime reason; `ci.yml` and `README.md` updated to install both files for lint/test, `Dockerfile` needed no change (it only ever installed `requirements.txt`). Two other candidates — `GET /trips/{id}/calendar.ics` + its Next.js proxy route, and `GET /auth/google-calendar-status` — looked unreachable (nothing in the current UI links to either) but turned out to be **intentional** retentions from the same-day Export Plan merge, not oversights; kept as-is after confirming with the user rather than unilaterally deleting a documented product decision (see the Itinerary export and Auth rows below). Full backend suite still 180 passed, frontend lint/typecheck still clean, real `docker build` verified. See [`docs/sessions/2026-08-26-codebase-cleanup.md`](docs/sessions/2026-08-26-codebase-cleanup.md). **Deliberately not touched**: `datetime.utcnow()`'s Python 3.12+ deprecation warnings (360 across the test suite) — naive UTC datetimes are this project's documented, project-wide convention (see `backend/pyproject.toml`'s `DTZ` ruff-ignore comment); switching every call site to timezone-aware datetimes is a real architectural decision, not a cleanup-pass side effect. |
| UI styling: plain hand-written CSS → **Tailwind CSS v4 + shadcn/ui**, 2026-08-29 | User asked for the UI to look better; chose the shadcn/ui option over two lighter alternatives (polish the existing plain CSS, or Tailwind alone) when asked. `frontend/src/app/globals.css`'s ~350 lines of bespoke BEM-ish classes (`.sidebar`, `.chat-message__bubble`, `.day-card`, etc.) are gone, replaced by Tailwind utility classes directly in each component plus shadcn primitives (`components/ui/button|card|textarea|badge|separator|scroll-area|accordion|alert.tsx`) for anything with real interaction/accessibility behavior (accordion expand/collapse, focus rings). All 6 existing components (`Sidebar`, `ChatApp`, `ChatMessage`, `ChatInput`, `TripView`, `CalendarPushButton`) and both auth-adjacent pages (`login/page.tsx`) were rewritten on top of this — same props, same state, same server-action calls, same gating rules (export hidden until `start_date` resolves, etc.); this was a styling pass, not a behavior change, and was verified as such. This shadcn CLI generation (v4.19, the "base-nova" preset) uses `@base-ui/react` (MUI's headless primitives library) under the hood, not Radix — a newer default than most existing shadcn writeups assume; don't be surprised finding `@base-ui/react/*` imports instead of `@radix-ui/*` in `components/ui/*.tsx`, and note its API shapes sometimes differ from Radix's (e.g. Accordion takes a boolean `multiple` prop, not Radix's `type="single"|"multiple"`). **Palette**: replaced both the old bespoke `--accent` (`#ff4b4b`, a leftover from the pre-Next.js Streamlit app's default theme color, never a deliberate product choice) and shadcn's own default grayscale `--primary` with a teal ("ocean/exploration") accent — Tailwind's own teal-700/teal-400 oklch stops (light/dark respectively), not hand-picked hex, so contrast at each lightness is already tuned. Dark mode stays **`prefers-color-scheme`-driven, no toggle, no `next-themes` dependency** — shadcn's `init` scaffolds a JS-class-based `.dark` selector by default (for a theme switcher this app doesn't have and wasn't asked for), so those generated values were moved under a media query instead, keeping the app's original zero-JS-theming behavior. Also fixed a real pre-existing bug while wiring this up: `--font-sans` was never actually set to the Geist font `layout.tsx` loads via `next/font` (it only set `--font-geist-sans`, a different variable), so the loaded font was silently unused and every element fell back to the browser default sans stack; now wired through correctly. **Real mobile-layout bug found and fixed live, not by inspection**: the outer `.app-layout` flex row (sidebar + main side-by-side, sidebar a fixed 260px) never had a narrow-viewport case in the original app either — confirmed live at a 375px width via the in-app browser that the sidebar's fixed width pushed the entire chat panel off-screen, invisible rather than merely cramped. Fixed with a pure-CSS breakpoint (`flex-col` below `md`, `md:flex-row` at/above it; sidebar `w-full` → `md:w-64`; its conversation list capped to a `max-h-48` scrollable region on mobile instead of pushing the chat down indefinitely) — no JS, no drawer/hamburger state, consistent with keeping this a "few moving parts" hobby-scale app. Verified via a temporary local-only preview route (mock data, deleted before finishing, never committed) rather than the real Google OAuth flow, across light, dark, desktop, and mobile (375px) — real `tsc --noEmit`, `eslint`, and `next build` all clean afterward. New dependencies, all from the standard shadcn/Tailwind v4 install path, not hand-picked piecemeal: `tailwindcss`/`@tailwindcss/postcss`/`postcss`, `@base-ui/react`, `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react` (icons), `tw-animate-css`. |
| Product hardening pass, 2026-08-31 | User explicitly corrected the framing here — this is a real product's base, not a hobby/side project — after an initial architecture review leaned on "hobby scale" language; that correction recalibrated the priority of everything below (see `docs/sessions/2026-08-31-cors-rate-limiting-and-tier1-hardening.md` for the full write-up). **Tier 0 (shipped same day)**: `main.py`'s `allow_origins=["*"]` replaced with an env-driven `ALLOWED_ORIGINS` allow-list (defaults to the local Next.js dev origin; nothing in this app's own architecture needs a browser to call the backend cross-origin at all — the frontend only ever reaches it via Next.js Server Actions); new `rate_limit.py` (slowapi, IP-keyed) adds a 100/minute app-wide default plus a stricter 10/minute cap on `POST /trips/generate` specifically, since that route always makes at least one real LLM call. In-process/in-memory — real protection today, but not shared across replicas if the backend is ever horizontally scaled (see that file's docstring for the Redis-backed upgrade path). **Tier 1 (shipped same day)**: every foreign-key column in `models.py` gained `index=True` (Postgres never auto-indexes these) — migration `98900a8d691c`, applied live to Neon and verified via `information_schema`; `routers/conversations.py::get_conversation` now `selectinload`s the `messages -> trip -> items` chain and only runs a real freshness check (`weather_service.get_or_refresh_trip_weather`) for a conversation's *latest* trip, serving every older trip from a new cache-only `weather_service.read_cached_weather()` — previously every trip-bearing message got the full freshness-check-and-possible-live-fetch treatment on every single conversation reload, scaling with edit count for no benefit; `list_conversations` gained `limit`/`offset` query params (default 100, hard-capped at 200, FastAPI itself 422s above that) since it was previously unbounded; new `usage_quota.py` + `User.daily_request_count`/`daily_request_count_date` (migration `4e14c7bab841`, applied live to Neon) add a real per-account daily cap (`DAILY_TRIP_GENERATION_LIMIT`, default 20/day) on `POST /trips/generate`, checked before `classify_intent` or any other LLM work runs (the same "gate before anything expensive runs" discipline as principle #1, one step earlier) — deliberately DB-backed, not in-memory like `rate_limit.py`'s limiter, specifically so the cap holds even if the backend is ever scaled to multiple instances. Both new migrations were autogenerated against the live Neon schema, reviewed before applying (the quota-columns one needed a hand-added `server_default=sa.text('0')` — the same nullable-column-with-no-default incident class this file already documents for the `tour_guide_mode` migration, caught the same way), then applied live and verified. **Explicitly deferred, not done this session**: real observability/error tracking, load-verifying the Groq fallback, budgeting a paid Gemini tier, confirming Neon's backup/PITR posture, and moving secrets out of plaintext `.env` for the real deploy target — all still-open Tier 0 items from the same review. **Tier 2 (shipped same day, `docs/sessions/2026-08-31-tier2-agent-service-cleanup.md`)**: `agent_service._run_tool_loop`'s previously-silent failures (an outright exception, or exhausting `MAX_TOOL_ROUNDS` with no final answer) now `logger.exception`/`logger.warning`, tagged with which of the three loops (`currency`/`qa_place_context`/`planning_place_context`) actually failed — the `""`-to-the-caller contract is unchanged, this only adds log visibility that didn't exist before for loops that are on by default in production. New `gemini_client.py` now owns Gemini client construction/`GEMINI_MODEL`/thinking-config, shared by both `llm_service.py` and `agent_service.py` — removes `agent_service.py`'s previous reach into `llm_service.py`'s underscore-prefixed internals (`_get_client()`/`GEMINI_MODEL`/`_THINKING_CONFIG`) for the same three things, which was also this codebase's one circular import (`llm_service` imports `agent_service` for the itinerary-planning gather step; `agent_service` imported `llm_service` right back, for this and only this) — `agent_service.py` no longer imports `llm_service` at all, verified live via a fresh interpreter import. `llm_service.py` re-exports the three names as aliases onto `gemini_client` so the existing test suite's `patch("app.llm_service._get_client", ...)` call sites needed zero changes. Tier 2's third item (sequential per-chunk itinerary generation for long trips) deliberately left alone — a real latency trade-off against the existing anti-repetition mechanism, not a bug. |
| Itinerary export: **.ics only, built 2026-08-26** — PDF deferred | Build-order item 3. New `calendar_export.py` (pure formatting, no LLM, no network call) builds one `VEVENT` per `ItineraryItem` via the `icalendar` library (pinned `==7.3.0`, the current stable release verified on PyPI at build time — pure Python, no transitive network-calling deps). Each event's real date is `trip.start_date + (day_number - 1)`, plain Python arithmetic (principle #6's discipline, even with no LLM anywhere near this feature). Exposed as `GET /trips/{trip_id}/calendar.ics` in `routers/trips.py`, returning `404` for an unknown trip and `400` when `trip.start_date` is `None` (a defensive check for direct API callers — the UI never surfaces an export control in that state at all, see below). **Deliberately floating local time, no `TZID`**: no reliable per-destination timezone is available at this layer without a second geocode call (`weather_service`'s Open-Meteo request resolves one internally via `timezone=auto`, but that value never surfaces past that module), and floating time is valid, correct RFC 5545 behavior for "9am in Lisbon" regardless of the importing calendar app's own timezone — revisit only if a real user complaint surfaces, not speculatively. `time_of_day` (freeform text — "morning", "14:00", "flexible", or `None`) is resolved to a real clock time via a small regex-plus-keyword heuristic (literal 24h/12h times first, then a fixed keyword table — "late morning" checked before the plainer "morning" so more specific phrasing wins), the same "small keyword lookup, not an LLM call" style also used by the frontend's `lib/weatherIcon.ts`; anything unrecognized (including `None`) becomes an all-day event rather than a guessed time. Timed events get a fixed 2-hour default duration (items carry no explicit length). **Frontend gating, per explicit product decision**: the export control is hidden entirely, not disabled, until a trip has a resolved `start_date` — no fallback-to-today, no error state shown to the end user. **Updated for the Next.js migration, 2026-08-26** (originally built against the Streamlit UI, ported during Phase A with the same gating rule preserved). **Superseded in the UI the same day, after Phase D**: the dedicated `.ics` download button (`ExportButton.tsx`) was removed in favor of a single "Export Plan" action that pushes straight to Google Calendar (`CalendarPushButton.tsx`, see the Auth decision row's Phase D follow-up) — the backend endpoint (`GET /trips/{trip_id}/calendar.ics`) and its Route Handler proxy (`app/api/trips/[tripId]/calendar/route.ts`) are untouched and still work if hit directly, nothing in the UI just links to them anymore. `TripResponse.start_date` was added to `schemas.py` and threaded through all three places a `TripResponse` is built from a real `Trip` row (`generate_trip`, `get_trip`, `conversations.py::get_conversation`) specifically so the frontend has this to gate export on without guessing — that gating rule (hidden entirely, not disabled, until `start_date` resolves) carried over unchanged to `CalendarPushButton`. |

## Architecture principles

Apply these to every new tool/integration, not just the ones that exist today.

1. **Classify before anything expensive runs.** `classify_intent` exists so
   cheap questions and off-topic messages never hit the full
   itinerary/agent pipeline. Gate new capabilities the same way — don't
   bolt them onto the main generation path unconditionally.
2. **Tools return small, flat, pre-aggregated JSON — never raw provider
   payloads.** `tools.py`'s `convert_currency` reduces a Frankfurter response
   to 4 fields (the removed weather tool used to do the same, reducing a
   40-entry OpenWeather response to 3 arrays — same standard applies
   whenever weather or any other tool comes back); every new tool (Maps,
   flights, hotels, calendar) should do the same kind of reduction before
   its output reaches a prompt. This is a cost control once tokens cost
   real money, not just tidiness.
3. **Split client vs. tool.** Raw API wrapper (auth, retries, pagination) is
   a different layer from the LLM-facing tool function (shaped output,
   schema-described, never raises — returns `{"error": ...}` like the
   existing tools do). Once there's more than one integration, use
   `clients/` + `tools/`, not one flat file.
4. **Cache tool calls.** Same args within a short window (same city+dates)
   should hit a TTL cache, not the live API again. Required, not optional,
   once running against rate-limited free tiers (Gemini, Maps).
5. **Findings gathered once should serve the whole conversation, not be
   re-fetched per turn — and every consumer must actually read the
   cache.** This is why `Conversation.agent_context` exists, and why
   `answer_question` had to be fixed to read it (it was being written but
   never read, so follow-up questions had no real data and the model
   invented numbers). Any new cached-findings feature needs both halves —
   write *and* read — checked explicitly.
6. **Never let the LLM do date arithmetic.** Inject `current_date` into
   every prompt as a fact. Resolve relative expressions ("next weekend,"
   "in two weeks") with real Python (`dateutil`), not model reasoning.
7. **Don't let the model invent data it wasn't given.** Prompts referencing
   real-world facts (weather, prices) must instruct the model to say "I
   don't have that" instead of guessing — **unconditionally**, not just when
   real data happens to already be available (a gap that let `answer_question`
   fabricate a whole invented forecast, wrong units included, when nothing
   was cached yet). Ground prompts in real fetched data whenever it's
   available, and when it's not, actually go try to fetch it rather than
   settling for a bare "I don't know" if the answer is gettable —
   `answer_question`/`gather_trip_context`'s on-demand-fetch-when-nothing's-
   cached handling is the reference pattern for both halves of this.
8. **Prefer MCP for new external tool integrations, when a trustworthy
   server exists.** As of Aug 2026, Google ships fully-managed, officially
   supported remote MCP servers for both Calendar (`calendarmcp.
   googleapis.com`) and Maps (via Google Maps Platform), and `google-genai`'s
   Python SDK has experimental native MCP support — pass an
   `mcp.ClientSession` straight into `GenerateContentConfig(tools=[...])`
   and Gemini both discovers the server's tools and calls them, largely
   replacing the hand-rolled `FunctionDeclaration` schema + manual
   round-trip loop that `agent_service.py`/`tools.py` use today for
   currency. This does **not** mean tools "talk to the LLM directly"
   bypassing the backend — the backend is still the MCP *client*: it still
   owns the connection to each MCP server (remote HTTP or a self-hosted
   subprocess), still routes results through Gemini, and still needs the
   same anti-fabrication grounding (principle #7) regardless of transport.
   What MCP actually buys: less hand-written REST-wrapper code, and a
   standard shape that scales to more integrations without every one
   becoming a bespoke client. Decide per integration, not blanket:
   - An **official, managed, remote** MCP server (HTTP/OAuth, e.g.
     Calendar's) is the easy case — no subprocess to run, no third-party
     code to vet, roughly interchangeable with hand-rolling the same calls
     via `googleapiclient`.
   - A **self-hosted third-party** MCP server (stdio subprocess/container,
     e.g. a community Open-Meteo weather server) trades hand-written REST
     code for a Docker Compose service and a third-party codebase you now
     have to trust and keep updated — evaluate it like any new dependency,
     don't add one uncritically just because it exists.
   - A **small MCP server we write ourselves** is often better than
     importing a third-party one when the tool surface is narrow — one
     purpose-built tool with the exact flat/pre-aggregated shape
     principle #2 already requires, versus a generic multi-tool community
     server with more surface area (and more to trust) than the app needs.
   - `google-genai`'s MCP support is **experimental** — re-verify it's
     graduated (or learn its current limitations) before depending on it
     for anything load-bearing, same as every other dated fact in this
     file.

## MVP build order

Cheapest / most self-contained first, most external-dependency risk last.
Don't reorder without discussing it — this reflects real cost/risk
tradeoffs from the decision log above, not arbitrary sequencing.

1. Bug/correctness pass — **ongoing discipline, not a one-time step.**
   Don't mark this "done" again; treat every session as a chance to catch
   another one before building net-new scope. Rounds shipped so far: agent
   findings (weather/currency) over-surfacing into every conversation turn;
   Q&A fabricating weather data (wrong units, invented conditions) when
   nothing was cached, fixed with an unconditional anti-fabrication
   instruction *and* an on-demand fetch when a question needs real data and
   nothing's cached yet (see principle #7 and `answer_question`/
   `gather_trip_context`); weather still wasn't working reliably even after
   that fix, so it was removed and the whole agent tool-calling step paused
   (see decision log) rather than sunk further into this round. **New
   round, 2026-08-25** (after real per-day weather came back, see decision
   log): confirmed live that a follow-up question ("what outfits would you
   suggest based on the weather") got answered with plausible-but-wrong
   temperatures (~70-80°F) against a real 104-108°F forecast, because the
   real `Trip.weather_json` data was never passed to `answer_question` at
   all -- only the currency-only `agent_context` was, a completely
   separate mechanism. Fixed by having `routers/trips.py`'s question
   branch look up the conversation's latest trip's weather on *every*
   question turn (cheap: `weather_service` caches internally, unlike the
   currency agent step which is a real Gemini call and stays cache-once-
   per-conversation) via the new `weather_service.summarize_for_prompt`,
   combined with the existing agent_context before reaching the model.
   Re-verified live against the exact reported prompt after the fix: the
   same follow-up now correctly cites 104-108°F. **Same day, next round**:
   a second real gap found live -- "4 days from now" (vs. the already-
   handled "in 4 days") silently resolved to no start date at all, so
   weather never activated and the model correctly said it had no data
   rather than guessing (the anti-fabrication path worked as designed --
   this wasn't a fabrication bug, it was a date-phrase coverage gap).
   `date_resolver.py` now also matches "N days/weeks from now/today", not
   just "in N days/weeks". Also checked live whether the prompt's "reyjevik"
   typo was a contributing factor (Open-Meteo's geocoder does fail on it,
   confirmed) -- it wasn't, in this case: `_infer_trip_meta`'s Gemini call
   already normalizes the destination before it ever reaches
   `weather_service.geocode`, confirmed by the assistant's own itinerary
   summary correctly saying "Reykjavik". A destination typo the model
   *doesn't* catch remains a latent, unconfirmed risk -- geocoding has no
   fuzzy-match fallback -- but isn't worth solving speculatively without a
   real case. **Third round, 2026-08-26** -- same visible symptom
   ("I don't have weather data") as the two rounds above, but a genuinely
   different bug from either: a trip generated with no date phrase at all
   ("build me a 5 day trip to austin") correctly has `start_date = None`,
   and a follow-up question that *itself* named a date ("what do the
   temperatures look like ... this weekend") still got the no-data reply,
   because `routers/trips.py`'s `question` branch never called
   `date_resolver.resolve_trip_start_date` on anything, ever -- it only
   ever read the trip's already-resolved `start_date`, which generation
   left `None`. Unlike round one (data existed, wasn't passed through) or
   round two (the resolver's regex didn't recognize a phrasing), this was a
   code path that had never had date-resolution logic in it at all, so no
   amount of regex coverage in `date_resolver.py` could have helped. Fixed
   by trying `date_resolver.resolve_trip_start_date(request.prompt, ...)`
   on the question's own text when `latest_trip.start_date is None`, and
   persisting the resolved date onto the trip (so it also unlocks weather
   for later turns and the `.ics` export button, not just this one
   answer -- principle #5). See
   [`docs/sessions/2026-08-26-qa-date-bug-and-currency-pause.md`](docs/sessions/2026-08-26-qa-date-bug-and-currency-pause.md)
   for the full write-up and a follow-up audit for the same divergence
   pattern elsewhere: it found one more real instance (weather always
   geocodes `trip.destination`, never a different city named in a
   follow-up question -- left open, no existing deterministic extractor to
   reuse the way `date_resolver.py` was here) and one instance that's now
   moot (currency's cache-once-per-conversation gate has the same shape,
   but currency itself is paused as of the same day, see decision log).
   **Fourth round, 2026-08-27** — two unrelated bugs found through live
   use, both fixed with grounded prompt changes (never hard logic) and
   live-verified against real Gemini calls: (a) `_infer_trip_meta`
   re-guessed `total_days` from scratch on every call including edit
   turns, with nothing anchoring it to an already-established day count —
   "Plan a 5 day trip to Miami" → "I want to experience the artsy miami"
   (no day-count language) silently became 3 days. Fixed the same way
   `start_date` already handled this exact shape of problem: look up the
   conversation's previous `Trip`'s day count and fold it into the meta
   prompt as a soft, overridable fact ("keep it at N unless the request
   explicitly asks for a different length"), not a hard override — day
   count must stay changeable by text alone, there's still no UI field for
   it (see the "Trip length" row below). (b) `classify_intent`'s prompt
   had zero few-shot examples, so "be my tour guide"/"take me through this
   place" (asked about a place already discussed) was classified
   `edit_trip`/`new_trip` instead of `question`, regenerating a brand-new
   itinerary instead of reaching `agent_service.answer_question_with_tools`/
   `get_place_context` at all — confirmed live that the Q&A tool path
   itself was already correctly instructed to handle this phrasing (its
   system prompt and the tool's own schema description both already say
   `detail="detailed"` for "be my tour guide"), so splitting the Wikipedia
   tool (the user's initial hypothesis) would not have fixed it. Fixed by
   adding concrete inline examples to `INTENT_INSTRUCTIONS` distinguishing
   explicit itinerary-edit requests from narrative/tour-guide phrasing.
   Both fixes live-verified against the exact reported scenarios, plus
   verified neither one over-corrected (an explicit "make it a full week
   instead" still changes day count; an explicit "swap day 2 for something
   food-focused" still regenerates the itinerary). **Same-day follow-up**:
   investigated a suspected third bug (fabricated-sounding specific venue
   names/addresses in a "be my tour guide" answer) by instrumenting
   `answer_question_with_tools` directly and replaying the scenario ~9
   times — found `get_place_context` was reliably called and correctly
   grounded, and the fabricated content was actually the misrouting bug's
   pre-fix output (a regenerated itinerary), not a separate issue, *except*
   for one real gap found live: `QA_TOOL_SYSTEM_PROMPT`'s anti-fabrication
   instruction only covered a tool call returning an `"error"`, not a
   *successful* call getting padded with invented extra venue
   names/addresses in `detail="detailed"` mode. Fixed with an explicit
   "only name a venue that came from the tool result or conversation
   history" instruction, re-verified live across 4 more runs with no
   invented venues. See
   [`docs/sessions/2026-08-27-day-count-drift-and-tour-guide-misrouting.md`](docs/sessions/2026-08-27-day-count-drift-and-tour-guide-misrouting.md).
   **Fifth round, 2026-09-01** — a real user-reported conversation surfaced
   the same failure *category* as the Fourth round above, recurring on
   phrasing variants `INTENT_INSTRUCTIONS` still didn't cover: (a) "I think
   i am already at wynwood walls i really want understand the importaance
   of the place" — a physically-present narrative/deep-dive request — did
   not set `tour_guide_requested`, because the trigger list only recognized
   the literal "be my tour guide"/"take me through this place" phrasing;
   (b) two turns later, "That is great i want to go somewhere to read a
   book can you suggest a place where i can go but still see the murals" —
   a request to recommend ONE nearby spot — was misclassified as
   `new_trip` and generated a brand-new, unrelated 5-day Miami itinerary
   ("Arrive in Miami and check into your hotel..."), ignoring that the
   user had just said they were already there. Fixed the same way the
   Fourth round was — concrete inline examples added to
   `INTENT_INSTRUCTIONS`, not hard logic — covering both a
   physically-present narrative trigger and an explicit `question`-vs-
   `new_trip` disambiguation for single-place recommendation asks (which
   contain travel-adjacent words like "go somewhere" without actually
   asking to plan a trip). Live-verified against the exact reported
   transcript, before and after: `tour_guide_requested` now correctly
   `True` for message (a), and message (b) now correctly stays `question`
   — the full `answer_question_with_tools` call for it returns a real,
   grounded recommendation (naming actual nearby cafés) instead of
   regenerating an itinerary. Also live-verified no over-correction: a
   genuine "plan me a week in Tokyo," an explicit "make it a week
   instead," and an explicit "be my tour guide" all still classify
   correctly. See
   [`docs/sessions/2026-09-01-intent-misclassification-recommendations.md`](docs/sessions/2026-09-01-intent-misclassification-recommendations.md).
   **Sixth round, same day** — a different, unrelated mechanism from the
   same live conversation: a user correctly got a real, grounded scuba-
   diving answer (Florida Keys, Florida Reef Tract, Biscayne National
   Park), then said "can we add to the plan" — the regenerated itinerary
   had zero mention of diving anywhere. Root cause was not classification
   this time (the message correctly hit `edit_trip`) but
   `routers/trips.py::_build_conversation_context`'s char-budget
   truncation: it joined the last `MAX_CONTEXT_MESSAGES` in chronological
   order, then applied a plain `[:MAX_CONTEXT_CHARS]` slice — keeping the
   **oldest** content and silently dropping the **newest** once the
   budget was exceeded. Reproduced exactly with the real message content:
   the 1000-char cutoff landed mid-sentence through the scuba answer,
   dropping every relevant keyword before `generate_itinerary`'s
   `conversation_context` ever saw it. Fixed by building the string from
   the most recent message backward (dropping the oldest first when
   over budget), then restoring chronological order — the most recent
   turn, which any "add to the plan"-style follow-up refers to, is now
   never the part that gets cut. Live-verified: the fixed context
   preserves the scuba content intact, and a real `generate_itinerary`
   call with it produces an itinerary that actually includes a Florida
   Keys diving day and a Biscayne National Park day. Shared by both
   `classify_intent` and itinerary generation (same function, same
   truncated string), so this fix benefits intent classification on long
   conversations too, not just the edit_trip path where it was first
   observed. See
   [`docs/sessions/2026-09-01-conversation-context-truncation-bug.md`](docs/sessions/2026-09-01-conversation-context-truncation-bug.md).
2. Gemini swap (structured output + native tool calling) — **done** (see
   decision log for the concrete `gemini-3.6-flash`/`thinking_level`/
   `role="user"` corrections found only by actually building it). The agent
   tool-calling step (currency only — weather stays removed) was
   re-enabled and verified live 2026-08-25, then **paused again
   2026-08-26** — a product decision that currency isn't needed, not a
   reliability finding — see decision log.
3. Itinerary export (.ics / PDF) — zero external dependencies, no quota risk.
   **.ics — done, 2026-08-26** (see decision log); PDF not built, deferred
   indefinitely rather than pulled into this round.
4. Maps/routing integration (OSM-based: Nominatim + Overpass +
   OpenRouteService + Open-Meteo + Wikipedia — see decision log) — real
   coordinates, distances, travel time, place importance, and a per-day
   energy/pacing signal. Moved up from its earlier position after Google
   OAuth+Calendar: it no longer needs a Google Cloud project or billing
   account, so it doesn't need to wait on OAuth setup. OpenRouteService
   needs one free signup (API key, no card). Plan drafted, not yet built.
   **Superseded by the Aug 2026 decision-log reversal** (see decision log):
   now planned as Google's official Maps MCP server, not the OSM stack. The
   rationale that originally moved this item up — "no longer needs a Google
   Cloud project or billing account" — no longer holds, since Maps MCP needs
   the same billing-enabled Google Cloud project as Calendar (item 5). Worth
   reconsidering whether Maps and Calendar/OAuth should now be
   sequenced/built together given that shared prerequisite — flagged here,
   not resolved; don't resequence without discussing it first.
5. Google login (OAuth) + Google Calendar push — **done, 2026-08-26**,
   moved ahead of item 4 (Maps) by explicit request, not a silent reorder.
   All four phases shipped: A (Next.js migration), B (Auth.js + JWT
   bridge), C (real per-user data isolation), D (Calendar push — via
   `googleapiclient` directly, not the Calendar MCP server originally
   planned; see decision log's Calendar and Auth rows for why that
   reversed). Item 4 (Maps) stays unbuilt. **Not yet live-tested with a
   real Google account** — every phase was verified as far as possible
   without one (up to Google's own `invalid_client` rejection of
   placeholder OAuth credentials); a human still needs to create a real
   Google Cloud OAuth client before this is actually usable end-to-end.
6. Flights / hotels — last; scoped down per the decisions above, the most
   expensive and least "free" part of the product.
7. Cross-trip preference memory (pgvector) — only after the above works;
   materially different from within-conversation memory, don't pull forward
   without a specific reason to.

## Constraints to keep in view

- **Budget is $0** unless explicitly told otherwise. Every new integration
  should be evaluated against a real, currently-live free tier — not a
  remembered one. These change (see the Amadeus shutdown, Google Maps'
  retired $200 credit) — verify before committing to one in a real change.
- Free-tier numbers in this file are dated **Aug 2026**. Re-verify before
  relying on a specific figure for a real decision, and update this file
  when the facts change.

## Commands

See [`README.md`](README.md) for first-time setup (API keys, Google OAuth
client, running with or without Docker) — this section is the quick
reference once that's done.

```bash
# Backend tests (in-memory SQLite, no live MySQL/GEMINI_API_KEY needed)
# requirements-dev.txt layers pytest/httpx on top of requirements.txt --
# the production image only ever installs the latter, see decision log's
# "Codebase cleanup pass" row.
cd backend && pip install -r requirements.txt -r requirements-dev.txt
cd backend && pytest -v

# Single test file / single test
cd backend && pytest tests/test_llm_service.py -v
cd backend && pytest tests/test_llm_service.py::test_classify_intent_new_trip -v

# Lint
cd backend && ruff check .

# Frontend dev server (needs BACKEND_URL -- see frontend/.env.local.example)
cd frontend && npm install && npm run dev

# Frontend lint / typecheck / production build
cd frontend && npm run lint
cd frontend && npx tsc --noEmit
cd frontend && npm run build

# Apply a schema migration (against whatever DATABASE_URL points at)
cd backend && alembic upgrade head
# On a brand-new DB that create_all() already built from scratch (so the
# columns already exist) -- mark migrations as applied without running them:
cd backend && alembic stamp head
# After changing models.py, generate the migration for it:
cd backend && alembic revision --autogenerate -m "description"

# Full stack locally
cp .env.example .env
docker compose up --build
```

On Windows, the system `python` is not `backend/.venv` — running `pytest`/
`ruff` directly (outside Docker/the activated venv) can silently resolve to
a different Python that's missing this project's dependencies (confirmed
live: a bare `ModuleNotFoundError: No module named 'jose'` during the
2026-08-26 cleanup pass). Use `backend/.venv/Scripts/python.exe -m pytest`
etc. explicitly, or activate the venv first.

Env vars (`.env`, see `.env.example`): `DATABASE_URL` (Neon Postgres — required, no default), `GEMINI_API_KEY`
(free tier, no card — aistudio.google.com/apikey), `GEMINI_MODEL`
(`gemini-3.5-flash-lite` default), `GROQ_API_KEY` (optional — free tier, no
card, console.groq.com/keys; enables the automatic fallback when Gemini's
quota is exhausted, see decision log), `GOOGLE_PLACES_API_KEY` (optional —
**billed**, needs a Google Cloud project with billing enabled; enables
`get_place_details`/`find_nearby_places`, see decision log's Place context
row — leave blank for Wikipedia-only place context), `BACKEND_URL` (frontend → backend),
`AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` (Google Cloud Console OAuth client,
needed for real login), `AUTH_SECRET` (Auth.js cookie encryption),
`AUTH_BACKEND_SECRET` (shared secret, exact same value needed by both
services — signs the JWT frontend→backend, see decision log's "Auth" row),
`TOKEN_ENCRYPTION_KEY` (Phase D, encrypts stored Calendar refresh tokens at
rest — generate with `python -c "from cryptography.fernet import Fernet;
print(Fernet.generate_key().decode())"`, not `openssl`, it must be a valid
Fernet key specifically). None of these are needed to run the test suite
itself.

**Before running `alembic revision --autogenerate` or `upgrade head`
against a real database, read the generated migration file.** A real
incident during Phase D: an earlier `ruff --fix` had silently deleted
`alembic/env.py`'s `from app import models` (flagged as "unused" since
nothing in that file references `models` by name — it's imported purely
for the side effect of registering every table on `Base.metadata`), which
made autogenerate think the target schema was empty and produced a
migration that would have dropped every table in the database. Caught only
by reading the generated file before applying it. If `alembic/env.py` is
ever touched by a lint auto-fix again, re-verify `target_metadata` still
resolves to a populated `MetaData` (see its own comment) before trusting
the next autogenerate.

## Repo map

```
backend/app/
  main.py              FastAPI app, loads .env, mounts routers
  models.py             SQLAlchemy models: User, Conversation, Message, Trip, ItineraryItem
  database.py            DB engine/session setup -- Neon Postgres, DATABASE_URL required (no default), see decision log
  scripts/migrate_to_neon.py  One-off MySQL -> Neon data migration script, kept for reference -- safe to delete once Docker MySQL is decommissioned
  llm_service.py          Gemini calls: intent classification, itinerary generation, Q&A -- falls back to groq_service.py on quota exhaustion, see decision log
  groq_service.py          Fallback LLM provider (Groq, OpenAI-compatible SDK), only invoked on a Gemini 429 -- see decision log
  agent_service.py        THREE tool-calling loops: gather_trip_context (currency, paused, kill switch off), answer_question_with_tools (conversational place-context, on by default, runs fresh every question turn), gather_place_context_for_itinerary (itinerary-planning place-context, on by default, runs once per conversation alongside currency) -- see decision log's Place context row for why they're kept separate
  tools.py                 Tool implementations + schemas (currency via Frankfurter, weather removed; three place tools -- get_place_context via clients/wikipedia_client.py, get_place_details/find_nearby_places via clients/google_places_client.py) -- per-loop schema subsets (CURRENCY_TOOL_SCHEMAS/QA_TOOL_SCHEMAS/PLANNING_TOOL_SCHEMAS), see decision log
  clients/wikipedia_client.py  Raw Wikipedia API wrapper (opensearch/summary/full-extract), free/keyless, lru_cache'd
  clients/google_places_client.py  Raw Google Places API (New) wrapper (text_search/place_details/nearby_search) -- billed, GOOGLE_PLACES_API_KEY's presence is the kill switch (PLACES_API_ENABLED), see decision log's Place context row
  date_resolver.py          Real-Python date extraction from the prompt (no LLM) -- see decision log
  weather_service.py        Open-Meteo geocode + per-day forecast, not a Gemini tool -- see decision log
  calendar_export.py        Builds a trip's .ics file (icalendar) -- pure formatting, no LLM/network call, see decision log
  auth.py                    Verifies the Next.js<->FastAPI bridge JWT (get_current_user dependency) -- see decision log, "Auth" row
  google_calendar.py          Calendar push via googleapiclient (Phase D) -- encrypted token storage/refresh, see decision log
  rate_limit.py               slowapi Limiter (IP-keyed) -- app-wide 100/min default + a stricter 10/min on POST /trips/generate, see decision log's "Product hardening" row
  usage_quota.py               Per-account daily cap on POST /trips/generate (User.daily_request_count), DB-backed so it holds across replicas -- see decision log's "Product hardening" row
  schemas.py                Pydantic request/response models (TripRequest, TripResponse, etc.)
  routers/trips.py         /trips/generate, GET /trips/{id}, GET /trips/{id}/calendar.ics, POST /trips/{id}/push-to-calendar -- all require auth + ownership
  routers/conversations.py  Chat history endpoints -- all require auth + ownership as of Phase C
  routers/auth.py            POST /auth/google-calendar-token, GET /auth/google-calendar-status (Phase D) -- no current UI caller, kept as a capability, see decision log's cleanup-pass row
backend/requirements.txt   Runtime deps only -- what the Docker image actually installs
backend/requirements-dev.txt  Adds pytest/httpx on top, for local dev + CI (see decision log's cleanup-pass row)
backend/Dockerfile         Backend image build (only installs requirements.txt, not the -dev file)
backend/alembic.ini        Alembic config (points at backend/alembic/)
backend/.dockerignore      Keeps .venv/tests/caches out of the build context
backend/alembic/          Schema migrations (added Phase B) -- see decision log for the create_all()-vs-migrations split
backend/tests/            pytest, in-memory SQLite, Gemini calls mocked; conftest.py overrides get_current_user for every test; test_ownership_isolation.py (Phase C), test_google_calendar.py + test_calendar_push_router.py (Phase D)
frontend/src/
  auth.ts                  Auth.js config: Google provider, JWT session strategy -- see decision log
  app/layout.tsx            Root layout (Server Component)
  app/page.tsx             Main chat page (Server Component) -- redirects to /login when unauthenticated
  app/login/page.tsx        Google sign-in page
  app/api/auth/[...nextauth]/route.ts  Auth.js's own route handler
  app/api/trips/[tripId]/calendar/route.ts  Proxies GET /trips/{id}/calendar.ics for browser download
  lib/backend.ts           Server Actions -- the only place that calls FastAPI, see decision log
  lib/authHeader.ts          Mints the short-lived backend-scoped JWT from the current session
  lib/mintBackendJwt.ts       Pure JWT signer, shared by authHeader.ts and auth.ts's jwt callback (Phase D)
  lib/authActions.ts          signOutAction, connectGoogleCalendarAction (incremental Calendar consent, Phase D)
  lib/types.ts                 Shared frontend types
  lib/weatherIcon.ts            Keyword-lookup weather icon/label mapping -- same "no LLM call" style as calendar_export.py's time-of-day heuristic, see decision log
  types/next-auth.d.ts        Auth.js session/JWT type augmentation
  components/              ChatApp, Sidebar, ChatMessage, TripView, ChatInput, CalendarPushButton ("Export Plan" -- see decision log)
  components/ui/            shadcn/ui primitives (button, card, textarea, badge, separator, scroll-area, accordion, alert) -- generated, styling baseline for new UI, see decision log's UI styling row
  app/globals.css            Tailwind v4 import + design tokens (teal palette, dark-mode media query) -- no more bespoke component classes, see decision log
docker-compose.yml         Full local stack (mysql + backend + frontend)
.github/workflows/ci.yml   Lint + test on push/PR; build & push images to GHCR on merge to main
docs/sessions/             Session-by-session history/learnings log -- see its README.md
docs/deployment-readiness.md  One-time deployment prep checklist + pruning candidates (2026-08-30, advisory, update/delete once actioned -- not kept current like this file)
docs/deployment-guide.md      Concrete step-by-step deploy walkthrough (backend: Cloud Run, frontend: Vercel) -- not yet executed as of writing
docs/security-review.md       Manual security pass findings (2026-08-30) -- CORS/rate-limiting/error-detail-leak items, points to /code-review ultra for a deeper multi-agent pass
docs/design-references.md     Links to published (private) design artifacts -- UX directions for web+app, the backend request-flow diagram -- not source of truth for implemented UI, the code is
docs/architecture.md          Visual (Mermaid) companion to this file's "Architecture" section above -- diagrams, not prose; this file is still the source of truth if they disagree
```
