# CLAUDE.md — AI Travel Planner

This file is the project's north star. If a session's direction starts drifting
from what's below — scope creep, a re-litigated decision, a "shortcut" that
contradicts a principle here — stop and re-read this file before continuing.
If a request would meaningfully change scope, sequencing, or one of the
decisions below, ask the user before proceeding rather than assuming the
original plan still holds.

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
  **currently paused** (`agent_service.AGENT_TOOL_CALLING_ENABLED = False`):
  weather (OpenWeather) wasn't working reliably in practice and was removed
  outright; currency conversion (Frankfurter) is still in `tools.py` but
  paused alongside it. `gather_trip_context()` short-circuits to `""`, so
  the rest of the pipeline (including the Q&A on-demand fetch and
  unconditional honesty instruction added for the weather-fabrication fix)
  behaves as if the agent step simply never finds anything — see decision
  log.
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

## Key decisions (with rationale — don't re-litigate without new information)

| Decision | Rationale |
|---|---|
| LLM: Mistral (local) → **Gemini** — **done** | Workable free tier for hobby scale, no card required. Gives native structured JSON output (`response_schema`) and native function calling, replacing the old hand-rolled markdown-fence JSON parser and Ollama-specific tool loop — confirmed delivered, not just aspirational (`_parse_json` is gone entirely). Concrete correction found only by actually trying it: `gemini-2.5-flash` (this row's original target) 404s for new API keys; migrated to `gemini-3.6-flash` instead, which is a reasoning model requiring `thinking_config.thinking_level=MINIMAL` to avoid burning the output-token budget on invisible thinking tokens, and whose function-response messages must use `role="user"` (`role="tool"` is rejected outright, despite that being Ollama's shape). Free-tier RPM/TPM/RPD numbers are no longer published in static docs (only live per-account in AI Studio) — re-verify via your own account before relying on a specific figure. |
| Database: MySQL → **Postgres on Neon** | pgvector lives in the same DB instance for the later cross-trip preference-memory feature — no separate vector service to run or pay for. Neon has no idle-pause gotcha (unlike Supabase's free tier). Trade-off accepted knowingly: Neon doesn't bundle free Auth the way Supabase would have, so auth is a fully separate build. |
| Auth: built **last** | Schema already supports it (`user_id` everywhere). When it happens: **Google OAuth** specifically — Maps and Calendar both need a Google Cloud project + OAuth consent anyway, so one login flow should cover identity + Maps scope + Calendar scope together, not three separate integrations. |
| Trip length: inferred from the prompt, no UI field | Explicitly rejected a "Trip length" slider/number-input in the Streamlit sidebar — say it in the message instead (e.g. "a week in Lisbon"). Don't re-add a form control for this without asking; it was tried and deliberately removed. |
| Weather (OpenWeather): **removed**; agent tool-calling step **paused** (currency too) | Wasn't working reliably in practice for real answers even after the fabrication/on-demand-fetch fix (root cause not fully diagnosed this round — the API key was present and valid-looking, so this wasn't simply a missing-key issue). Rather than leave a half-working agent step running with only currency left in it, the whole step is paused (`agent_service.AGENT_TOOL_CALLING_ENABLED = False`); `tools.py`'s `convert_currency` and its schema are kept in place, unused, for a cheap re-enable. `gather_trip_context()` returning `""` while paused is indistinguishable from "agent step ran, found nothing" to every downstream consumer, so no other code had to change. Re-diagnose weather from scratch (or reconsider the source — e.g. Open-Meteo, no key required, is already the pick for the drafted Maps/routing plan) before re-adding it. |
| Flights: no live pricing API for MVP | No workable free flight-pricing API exists as of Aug 2026 — Amadeus self-service, the obvious free option, was fully decommissioned July 17 2026. Treat flight cost as an LLM-reasoned rough estimate, clearly labeled as such, until there's budget for a paid API (~$10-20/mo — Duffel, AeroDataBox) or a better free option surfaces. Re-check the landscape before building against a live flights integration. |
| Hotels: search/compare only, not booking | Real reservations need PCI-compliant payment flows and hotel partner agreements — out of scope for a free-tier indie MVP. Deep-link out to Booking.com/Google Hotels rather than booking in-app. |
| Maps: OSM-based stack (Nominatim + Overpass + OpenRouteService + Open-Meteo + Wikipedia), not Google Maps Platform | Avoids requiring a Google Cloud billing account — Google Maps Platform needs one even at $0 spend (the same constraint that originally justified bundling Maps with OAuth setup below). The OSM stack is genuinely free with no card on file, at the cost of weaker geocoding accuracy for vague free-text place names and public shared-instance reliability (Nominatim: hard 1 req/sec cap across the whole app; Overpass: no SLA). Acceptable tradeoffs for a $0-budget hobby MVP. Full design: see the planned Maps/routing integration (deep per-item coordinates + legs, deterministic energy/pacing signal, grounded-not-invented importance notes) — plan drafted, not yet built. Re-verify free-tier terms before relying on specific figures, same as every other row in this table. |

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
   (see decision log) rather than sunk further into this round.
2. Gemini swap (structured output + native tool calling) — **done** (see
   decision log for the concrete `gemini-3.6-flash`/`thinking_level`/
   `role="user"` corrections found only by actually building it). Weather
   and the agent tool-calling step are still paused, independent of this —
   re-enabling them is a separate decision (next up, per this session).
3. Itinerary export (.ics / PDF) — zero external dependencies, no quota risk.
4. Maps/routing integration (OSM-based: Nominatim + Overpass +
   OpenRouteService + Open-Meteo + Wikipedia — see decision log) — real
   coordinates, distances, travel time, place importance, and a per-day
   energy/pacing signal. Moved up from its earlier position after Google
   OAuth+Calendar: it no longer needs a Google Cloud project or billing
   account, so it doesn't need to wait on OAuth setup. OpenRouteService
   needs one free signup (API key, no card). Plan drafted, not yet built.
5. Google login (OAuth) + Google Calendar push — bundled, one OAuth setup
   covers both. No longer needs to be bundled with Maps, since Maps moved
   off Google infrastructure (see above).
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

# Lint
cd backend && ruff check .

# Full stack locally
cp .env.example .env
docker compose up --build
```

## Repo map

```
backend/app/
  main.py              FastAPI app, loads .env, mounts routers
  models.py             SQLAlchemy models: User, Conversation, Message, Trip, ItineraryItem
  database.py            DB engine/session setup
  llm_service.py          Gemini calls: intent classification, itinerary generation, Q&A
  agent_service.py        Tool-calling loop run ahead of generation -- paused, see decision log
  tools.py                 Tool implementations + schemas (currency via Frankfurter; weather removed)
  routers/trips.py         /trips/generate — the main request path, ties everything together
  routers/conversations.py  Chat history endpoints
backend/tests/            pytest, in-memory SQLite, Gemini calls mocked
frontend/streamlit_app.py  Chat UI
docker-compose.yml         Full local stack (mysql + backend + frontend)
.github/workflows/ci.yml   Lint + test on push/PR; build & push images to GHCR on merge to main
```
