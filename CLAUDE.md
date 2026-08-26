# CLAUDE.md — AI Travel Planner

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

A chat-driven AI travel planner. Describe a trip in plain language, get a
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
  of 2026-08-26. Weather (OpenWeather) was removed outright on 2026-08-25
  because it wasn't working reliably in practice, and stays removed.
  Currency conversion (Frankfurter) was re-enabled the same day and verified
  live working correctly, but is paused again as of 2026-08-26 for a
  different reason — a product decision that it isn't needed, not a
  reliability problem (see decision log) — via the same kill switch flag,
  so `gather_trip_context()` short-circuits to `""` exactly as it did during
  its earlier pause.
- **Frontend**: Streamlit chat UI (`frontend/streamlit_app.py`). Deliberately
  minimal — no trip-length field or similar form controls; trip parameters
  come from the prompt text (see decision log, this was a deliberate
  reversal).
- **LLM**: Gemini API (`google-genai`), model `gemini-3.6-flash` by default
  (`GEMINI_MODEL` env var). Migrated off local Ollama/Mistral this session —
  native structured output (`response_schema`) replaced the hand-rolled
  markdown-fence JSON parser, native function calling
  (`types.FunctionDeclaration`) replaced the Ollama-specific tool loop in
  `agent_service.py`. `gemini-2.5-flash` (this file's original target) turned
  out to 404 for new API keys once actually tried — Google's own error
  redirects to `gemini-3.6-flash`; re-verify the current model string at
  `ai.google.dev/gemini-api/docs/models` if this starts 404ing again, model
  strings get retired without much notice.
- **Database**: MySQL, wired and working. **Migration to Postgres on Neon
  is decided but not done.**
- **Auth**: none yet, by design. Every request uses a placeholder `user_id`;
  every table already has `user_id` threaded through so this is cheap to
  retrofit later.

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

**Frontend** (`streamlit_app.py`) is a thin client: it never calls Gemini,
Groq, Open-Meteo, or Frankfurter directly — every one of those lives behind
`BACKEND_URL`. It POSTs to `/trips/generate` and lists/loads history via
`routers/conversations.py`'s endpoints, keeping `conversation_id` in
Streamlit session state.

## Key decisions (with rationale — don't re-litigate without new information)

| Decision | Rationale |
|---|---|
| LLM: Mistral (local) → **Gemini** — **done** | Workable free tier for hobby scale, no card required. Gives native structured JSON output (`response_schema`) and native function calling, replacing the old hand-rolled markdown-fence JSON parser and Ollama-specific tool loop — confirmed delivered, not just aspirational (`_parse_json` is gone entirely). Concrete correction found only by actually trying it: `gemini-2.5-flash` (this row's original target) 404s for new API keys; migrated to `gemini-3.6-flash` instead, which is a reasoning model requiring `thinking_config.thinking_level=MINIMAL` to avoid burning the output-token budget on invisible thinking tokens, and whose function-response messages must use `role="user"` (`role="tool"` is rejected outright, despite that being Ollama's shape). Free-tier RPM/TPM/RPD numbers are no longer published in static docs (only live per-account in AI Studio) — re-verify via your own account before relying on a specific figure. **One concrete figure this account actually hit, 2026-08-25**: `gemini-3.6-flash`'s free tier is capped at **20 requests/day** per project (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, confirmed via a live 429 after a day of testing) — easy to exhaust during active development (each `/trips/generate` call alone is 2+ Gemini calls: meta-inference + at least one chunk), not just real usage. A `502 Bad Gateway` from `/trips/generate` most likely means this, not a code/deploy problem — check the backend container logs for `RESOURCE_EXHAUSTED` before assuming otherwise. **Model swapped again, same day, 2026-08-25 — `gemini-3.6-flash` → `gemini-3.5-flash-lite`**, specifically to escape the above 20/day wall: `gemini-3.5-flash-lite` is a distinct model in Google's quota system (confirmed live — it answered successfully while `gemini-3.6-flash`'s daily cap was still exhausted) and passed every mechanical check live: clean `response_schema`/`.parsed` output, correct `start_day`/`end_day` chunk-range instruction-following, correct `convert_currency` function-calling (calls when useful, doesn't over-call when a prompt has no budget). **Google's open-weight Gemma 4 (`gemma-4-31b-it`, `gemma-4-26b-a4b-it`, also servable via the same Gemini API/SDK) was tried first and rejected** after live testing found real problems: `response_schema` didn't stop it from appending a trailing `` ``` `` markdown fence after the JSON (broke `response.parsed` entirely — Gemma answered `None`, the raw text needed manual `model_validate_json` and even then failed on the trailing fence), and it didn't reliably follow the explicit "write ONLY days N through M" chunk instruction (returned 1 day when 3 were asked for). The 26B-A4B (MoE) variant was worse still — a real degenerate token-repetition loop on part of a generated itinerary ("...-alonnage-alonnage-alonnage..." repeated dozens of times), not usable for user-facing content. Gemma 4 remains a real, notable option (Apache 2.0, self-hostable later, native function calling) but not a drop-in replacement without real prompt-engineering work first — don't re-attempt it as a quick fix without addressing both issues found here. `gemini-2.5-flash-lite` (an earlier candidate) is confirmed 404ing for new users as of this change, redirecting to `gemini-3.5-flash-lite` — that's already what's in use. |
| Database: MySQL → **Postgres on Neon** | pgvector lives in the same DB instance for the later cross-trip preference-memory feature — no separate vector service to run or pay for. Neon has no idle-pause gotcha (unlike Supabase's free tier). Trade-off accepted knowingly: Neon doesn't bundle free Auth the way Supabase would have, so auth is a fully separate build. |
| Auth: built **last** | Schema already supports it (`user_id` everywhere). When it happens: **Google OAuth** specifically — Calendar's MCP server needs a Google Cloud project + OAuth consent anyway (see Calendar row), so the login flow should cover identity + Calendar scope together. Maps MCP now also needs the same Google Cloud project for billing (see Maps row), though its exact auth mechanism (OAuth vs. a plain API key) isn't confirmed yet — if it turns out to be API-key-only, Maps doesn't need to be bundled into the user-facing OAuth flow itself, just the shared Cloud project/billing setup. Confirm before finalizing the OAuth build-order step. |
| Trip length: inferred from the prompt, no UI field | Explicitly rejected a "Trip length" slider/number-input in the Streamlit sidebar — say it in the message instead (e.g. "a week in Lisbon"). Don't re-add a form control for this without asking; it was tried and deliberately removed. |
| Weather (OpenWeather): **removed**; agent tool-calling step **re-enabled**, currency only | Weather wasn't working reliably in practice for real answers even after the fabrication/on-demand-fetch fix (root cause not fully diagnosed — the API key was present and valid-looking, so this wasn't simply a missing-key issue) and stays removed; re-diagnose from scratch (or reconsider the source — e.g. Open-Meteo, no key required, remains the pick regardless of the Maps-stack decision) before ever re-adding it. Currency conversion was paused alongside weather at the time rather than leaving a half-working step running, but has now been flipped back on (`agent_service.AGENT_TOOL_CALLING_ENABLED = True`, 2026-08-25) and verified live: a real Frankfurter call (500 USD → 60,624 ISK) was correctly picked up by the model, folded into a grounded summary with matching numbers, and — separately — a no-budget prompt correctly triggered no tool call at all rather than inventing one. `AGENT_TOOL_CALLING_ENABLED` stays as a kill switch if currency ever shows the same unreliability weather did. **Paused again, 2026-08-26 — for a different reason than weather's removal.** Currency was working correctly (the 2026-08-25 verification above stands); it's turned off now purely because of a product decision that currency conversion isn't needed, not a reliability finding. Same kill switch flag, flipped the other way (`AGENT_TOOL_CALLING_ENABLED = False`) — `gather_trip_context()` short-circuits to `""` again, no other code touched. A follow-up audit for the bug below's divergence pattern (generation-only logic missing from the Q&A path) also flagged that this tool-calling step's `Conversation.agent_context` gate caches "found nothing" per-conversation forever, so a later question that plainly needs a fresh currency figure would never get one — now moot with currency paused, but worth remembering if it's ever re-enabled. **Resolved, 2026-08-25 — weather is back, real-time, per-day, via Open-Meteo, and it's neither an MCP server nor a Gemini tool at all.** Evaluated community Open-Meteo MCP servers vs. building one ourselves vs. a plain `tools.py`-shaped function (per principle #8's decision rules) — landed on a fourth option once it became clear weather-to-*display* is never a judgment call the model makes (unlike currency, which the model opts into). It's a plain deterministic backend service (`date_resolver.py` + `weather_service.py`), called directly by `routers/trips.py`/`routers/conversations.py` on every trip, not registered in `tools.py`'s `TOOL_SCHEMAS`/routed through `agent_service.py` at all — so MCP's reason for existing (giving an LLM discoverable, callable tools) doesn't apply here, and the feature's marginal LLM cost is zero (no extra Gemini call, no extra tokens). Needed a new prerequisite that didn't exist at all: `Trip.start_date`, resolved from the prompt in real Python (`date_resolver.py`, regex-extracted date substrings + `dateutil`, never a whole-prompt fuzzy parse — that was tried first and confirmed live to misfire, e.g. "September 3rd" inside "...starting September 3rd" got polluted by an unrelated "5" elsewhere in the prompt into 2003-09-05) per principle #6. Verified live: real geocoding + a real Reykjavik forecast (7–11°C, overcast/light drizzle) came back correctly for a resolved date. Cached per-trip (`Trip.weather_json`/`weather_fetched_at`, 3-hour TTL) to stay well inside Open-Meteo's free 10,000/day cap regardless of how many times a trip is reloaded. **Fahrenheit added, 2026-08-25**: `weather_service._celsius_to_fahrenheit` computes both units with real Python arithmetic at fetch time (never left for the LLM to convert, same discipline as principle #6) — `DayWeatherOut` carries `temp_min_f`/`temp_max_f` alongside the existing Celsius fields, and the Streamlit display shows both ("High 11°C / 52°F"). **Threaded into conversational Q&A too, 2026-08-25** (see the bug/correctness-pass entry below for why): `routers/trips.py`'s question branch now looks up the conversation's latest trip's real forecast on every question turn and folds it into `answer_question`'s grounding via `weather_service.summarize_for_prompt` — `answer_question`'s system prompt was updated to allow stating the real Celsius/Fahrenheit figures exactly as given (not to invent a conversion when only one unit was provided, which is a different thing). **Known open gap, found in the same 2026-08-26 audit**: weather always geocodes `trip.destination`, never a different city named in a follow-up question ("what's the weather in Reykjavik this weekend?" against an Austin trip still answers for Austin) — left open, since unlike the date-resolution bug above there's no existing deterministic extractor to reuse; closing it needs either a new lightweight extractor or a fresh LLM call. |
| Flights: no live pricing API for MVP | No workable free flight-pricing API exists as of Aug 2026 — Amadeus self-service, the obvious free option, was fully decommissioned July 17 2026. Treat flight cost as an LLM-reasoned rough estimate, clearly labeled as such, until there's budget for a paid API (~$10-20/mo — Duffel, AeroDataBox) or a better free option surfaces. Re-check the landscape before building against a live flights integration. |
| Hotels: search/compare only, not booking | Real reservations need PCI-compliant payment flows and hotel partner agreements — out of scope for a free-tier indie MVP. Deep-link out to Booking.com/Google Hotels rather than booking in-app. |
| Maps: OSM-based stack → **reversed, Aug 2026 — switching to Google's official Maps MCP server** | Originally picked to avoid a Google Cloud billing account (Maps Platform needs one even at $0 spend). Reversed after Google shipped a fully-managed, officially supported Maps MCP server in 2026 (same wave as the Calendar MCP server below) that per Google's announcement bundles weather-forecast grounding alongside places/routing — potentially covering both the weather and Maps items on the future-tools list with one integration. Knowingly re-accepts the billing-account requirement the OSM pivot existed to avoid; judged worth it for an officially maintained server instead of hand-rolling and maintaining a 5-service OSM client (Nominatim/Overpass/OpenRouteService/Open-Meteo/Wikipedia) with its own reliability caveats (Nominatim's 1 req/sec cap, Overpass's no-SLA). **Unverified as of this decision** — Google's announcement didn't disclose Maps MCP pricing, free-tier limits, or exact auth flow (OAuth vs. API key); confirm all three before writing any code against it. The previously-drafted OSM-based Maps/routing plan (deep per-item coordinates + legs, energy/pacing signal, grounded importance notes) is superseded — re-derive the design against Maps MCP's actual tool surface once the above is confirmed, don't assume the old design transfers as-is. |
| Calendar: hand-rolled `googleapiclient` calls → **Google's official Calendar MCP server** (`calendarmcp.googleapis.com`) | Google shipped a fully-managed, officially supported remote Calendar MCP server in 2026 (OAuth 2.0, 8 tools: list calendars, retrieve events, check availability, create/update/delete events) — same prerequisite this project already needed anyway (a Google Cloud project + OAuth consent screen for the planned Google login), so adopting it costs nothing extra in setup and replaces what would've been hand-written `googleapiclient` calls with a maintained server. Still bundled with Google OAuth login exactly as originally planned (build order item 5) — unchanged by this decision, just the Calendar half is now MCP instead of a direct API client. |
| Reliability: **Groq added as an automatic fallback** when Gemini's quota is exhausted, 2026-08-25 | Direct response to the `gemini-3.6-flash` 20-requests/day wall above — a live demo can't be allowed to 502 mid-presentation. Groq's free tier (30 RPM / 6,000 TPM / **14,400 requests/day**, no card, no expiry) is ~700x that cap. Scoped to `llm_service.py`'s core paths only (`_call_gemini`/`_call_gemini_chat`, so every caller — intent classification, meta inference, chunk generation, Q&A — gets it automatically) and gated strictly on `_is_rate_limited` (HTTP 429 specifically) so a real bug (bad schema, invalid key, Google's servers down) still fails exactly as before rather than being masked by "well, Groq answered." Deliberately **not** wired into `agent_service.py`'s currency tool-calling step — that already degrades gracefully to `""` on any failure, so it's lower-stakes and out of scope. New `groq_service.py`, using the `openai` SDK pointed at Groq's OpenAI-compatible endpoint (principle #3: reuse an existing wrapper, don't hand-roll one) — model is `llama-3.3-70b-versatile`, deliberately **not Gemma 4** despite Gemma also being servable via Groq (see the row above: real problems found live). Anthropic Claude and OpenAI were evaluated and ruled out for this — neither has a persistent free API tier in 2026 (both give a one-time ~$5 trial credit, then pay-as-you-go), which doesn't sustain this project's $0 budget; revisit if that constraint ever changes. Groq's structured-output strict mode requires every schema property to be listed as required, which doesn't match this app's schemas (e.g. optional `notes` fields) — used in best-effort (`strict: false`) mode plus manual `model_validate_json` instead of fighting that mismatch. Not yet live-verified end-to-end (no `GROQ_API_KEY` was available to test with this session) — verified via mocked tests only; live-verify before relying on this for an actual presentation. |
| Itinerary export: **.ics only, built 2026-08-26** — PDF deferred | Build-order item 3. New `calendar_export.py` (pure formatting, no LLM, no network call) builds one `VEVENT` per `ItineraryItem` via the `icalendar` library (pinned `==7.3.0`, the current stable release verified on PyPI at build time — pure Python, no transitive network-calling deps). Each event's real date is `trip.start_date + (day_number - 1)`, plain Python arithmetic (principle #6's discipline, even with no LLM anywhere near this feature). Exposed as `GET /trips/{trip_id}/calendar.ics` in `routers/trips.py`, returning `404` for an unknown trip and `400` when `trip.start_date` is `None` (a defensive check for direct API callers — the UI never surfaces an export control in that state at all, see below). **Deliberately floating local time, no `TZID`**: no reliable per-destination timezone is available at this layer without a second geocode call (`weather_service`'s Open-Meteo request resolves one internally via `timezone=auto`, but that value never surfaces past that module), and floating time is valid, correct RFC 5545 behavior for "9am in Lisbon" regardless of the importing calendar app's own timezone — revisit only if a real user complaint surfaces, not speculatively. `time_of_day` (freeform text — "morning", "14:00", "flexible", or `None`) is resolved to a real clock time via a small regex-plus-keyword heuristic (literal 24h/12h times first, then a fixed keyword table — "late morning" checked before the plainer "morning" so more specific phrasing wins), the same "small keyword lookup, not an LLM call" style already used by `streamlit_app.py::_weather_icon`; anything unrecognized (including `None`) becomes an all-day event rather than a guessed time. Timed events get a fixed 2-hour default duration (items carry no explicit length). **Frontend gating, per explicit product decision**: the export control is hidden entirely, not disabled, until a trip has a resolved `start_date` — no fallback-to-today, no error state shown to the end user. It appears in two places in `streamlit_app.py`, both reusing one `_get_ics_bytes()` session-cached fetch: inline at the bottom of `render_trip()` right under the freshly generated itinerary, and as a persistent top-of-chat control (`_latest_exportable_trip()` scans the loaded conversation's messages newest-first for the latest trip with both a `trip_id` and a `start_date`). `TripResponse.start_date` was added to `schemas.py` and threaded through all three places a `TripResponse` is built from a real `Trip` row (`generate_trip`, `get_trip`, `conversations.py::get_conversation`) specifically so the frontend has this to gate on without guessing. |

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
5. Google login (OAuth) + Google Calendar push — bundled, one OAuth setup
   covers both. No longer needs to be bundled with Maps, since Maps moved
   off Google infrastructure (see above). Calendar side now planned via
   Google's official Calendar MCP server (see decision log) rather than
   hand-rolled `googleapiclient` calls; the OAuth/Cloud-project prerequisite
   is unchanged.
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

```bash
# Backend tests (in-memory SQLite, no live MySQL/GEMINI_API_KEY needed)
cd backend && pytest -v

# Single test file / single test
cd backend && pytest tests/test_llm_service.py -v
cd backend && pytest tests/test_llm_service.py::test_classify_intent_new_trip -v

# Lint
cd backend && ruff check .

# Full stack locally
cp .env.example .env
docker compose up --build
```

Env vars (`.env`, see `.env.example`): `DATABASE_URL` (MySQL), `GEMINI_API_KEY`
(free tier, no card — aistudio.google.com/apikey), `GEMINI_MODEL`
(`gemini-3.5-flash-lite` default), `GROQ_API_KEY` (optional — free tier, no
card, console.groq.com/keys; enables the automatic fallback when Gemini's
quota is exhausted, see decision log), `BACKEND_URL` (frontend → backend).
None of these are needed to run the test suite itself.

## Repo map

```
backend/app/
  main.py              FastAPI app, loads .env, mounts routers
  models.py             SQLAlchemy models: User, Conversation, Message, Trip, ItineraryItem
  database.py            DB engine/session setup
  llm_service.py          Gemini calls: intent classification, itinerary generation, Q&A -- falls back to groq_service.py on quota exhaustion, see decision log
  groq_service.py          Fallback LLM provider (Groq, OpenAI-compatible SDK), only invoked on a Gemini 429 -- see decision log
  agent_service.py        Tool-calling loop run ahead of generation -- re-enabled, see decision log
  tools.py                 Tool implementations + schemas (currency via Frankfurter; weather removed)
  date_resolver.py          Real-Python date extraction from the prompt (no LLM) -- see decision log
  weather_service.py        Open-Meteo geocode + per-day forecast, not a Gemini tool -- see decision log
  calendar_export.py        Builds a trip's .ics file (icalendar) -- pure formatting, no LLM/network call, see decision log
  schemas.py                Pydantic request/response models (TripRequest, TripResponse, etc.)
  routers/trips.py         /trips/generate — the main request path, ties everything together; also GET /trips/{id}/calendar.ics
  routers/conversations.py  Chat history endpoints
backend/tests/            pytest, in-memory SQLite, Gemini calls mocked
frontend/streamlit_app.py  Chat UI
docker-compose.yml         Full local stack (mysql + backend + frontend)
.github/workflows/ci.yml   Lint + test on push/PR; build & push images to GHCR on merge to main
docs/sessions/             Session-by-session history/learnings log -- see its README.md
```
