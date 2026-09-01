# 2026-09-01 — Google Places API integration

**Added two new billed Google Places tools (`get_place_details`,
`find_nearby_places`) alongside the existing free Wikipedia place-context
tool, so the QA and itinerary-planning loops can answer current/practical
questions and real nearby-place recommendations, not just history.**

## Changes shipped

- New [`backend/app/clients/google_places_client.py`](../../backend/app/clients/google_places_client.py)
  — raw Places API (New) wrapper (`text_search`, `place_details`,
  `nearby_search`), mirrors `wikipedia_client.py`'s shape. `GOOGLE_PLACES_API_KEY`'s
  presence is the de facto kill switch (`PLACES_API_ENABLED`) — unset it
  and the two new tools return `{"error": ...}` immediately, no network
  call, Wikipedia-only behavior unaffected. See CLAUDE.md's decision log
  for the full rationale (Wikipedia vs. Places division of responsibility,
  cost-control reasoning).
- [`backend/app/tools.py`](../../backend/app/tools.py) — `get_place_details`
  and `find_nearby_places` added, both reduce Google's raw payload to a
  flat pre-aggregated dict (principle #2), both wired into `QA_TOOL_SCHEMAS`
  and `PLANNING_TOOL_SCHEMAS` (the same two loops `get_place_context`
  already reaches); `CURRENCY_TOOL_SCHEMAS` untouched.
- [`backend/app/agent_service.py`](../../backend/app/agent_service.py) —
  `QA_TOOL_SYSTEM_PROMPT`/`PLANNING_TOOL_SYSTEM_PROMPT` extended with
  explicit guidance on which of the three place tools fits which kind of
  question, plus a cost-awareness clause for the two billed tools
  specifically (call at most 1-2 times per turn).
- `.env.example`/`.env` — `GOOGLE_PLACES_API_KEY` added, styled like the
  existing `GROQ_API_KEY` optional-key convention.
- Tests: new `backend/tests/test_google_places_client.py`; additions to
  `test_tools.py`, `test_agent_service.py` (schema-shape assertions now
  expect 3 place-tool declarations, not 1), `test_weather_service.py`
  (`TOOL_SCHEMAS` length 2 → 4). Full suite: 263 passed.

## Bugs found & fixed

- **Symptom**: a real end-to-end run of `answer_question_with_tools` for
  "Any good cafes near the Louvre in Paris?" returned an empty reply and
  logged `hit MAX_TOOL_ROUNDS (4) without a final answer`.
- **Root cause**: `find_nearby_places` resolved its `near` argument purely
  via `weather_service.geocode` (Open-Meteo), a city/place-name-oriented
  geocoder. It reliably failed on landmark-level phrasings ("Louvre
  Museum, Paris", "1st arrondissement Paris") that the model reasonably
  tried first. The model kept retrying with progressively broader
  guesses and only succeeded (bare "Paris") on the 4th and final allowed
  round — by which point `_run_tool_loop`'s round budget was exhausted, so
  Gemini never got a 5th call to actually read the successful result and
  answer. The tool itself worked; the round budget didn't survive the
  model's guessing.
- **Fix**: new `tools._geocode_for_places` helper — tries
  `weather_service.geocode` first (free), and falls back to Google Places'
  own `text_search` (which resolves landmark-level names directly,
  confirmed by `get_place_details` already working) when that fails.
  Resolves `near` deterministically in one call instead of leaving it to
  repeated LLM guesses across rounds — same "don't leave to chance what
  code can just handle" discipline principle #6 already applies to date
  arithmetic. Regression tests:
  `test_find_nearby_places_falls_back_to_places_text_search_when_geocode_fails`,
  `test_find_nearby_places_error_when_both_geocoders_fail`.
  Re-verified live after the fix: the same question now returns a real
  answer naming actual nearby cafes (Angelina, Le Procope, Café de Flore,
  Les Deux Magots), converging well within the round budget.

## Key learnings

- The user-supplied `GOOGLE_PLACES_API_KEY` was live-verified working
  (real `places:searchText` call for "Eiffel Tower" returned real rating/
  address data) before any code was written — confirms billing is enabled
  and Places API (New) access is active on that Google Cloud project.
- Places API (New)'s field-mask billing tiers are a real, concrete cost
  lever, not just a request-shaping nicety — `get_place_details`'s brief
  vs. detailed field masks intentionally differ in width for this reason.
- Live-verified all three place tools are correctly discriminated by the
  model based on question type in the same conversation flow: a
  current-status question ("is the Louvre open right now, and how is it
  rated?") correctly called `get_place_details` and reported the real 4.7
  rating and real "closed" status; a pure-history question ("why is the
  Louvre famous historically?") correctly stayed on `get_place_context`
  (Wikipedia) rather than reaching for a newer tool by default; a
  recommendation question correctly called `find_nearby_places` (after the
  fix above) and returned real named venues, not fabricated ones.
- Confirmed `weather_service.geocode` (Open-Meteo) and Google Places'
  `text_search` have genuinely different resolution strength — Open-Meteo
  handles city/region names well but not landmark-level strings; Places
  handles both. Worth remembering if a similar "resolve a place name"
  need comes up elsewhere in this codebase.

## Open items / follow-ups

- Scope was deliberately kept to place info + nearby search only — no
  routing/distance/directions — per an explicit user decision during
  planning, to avoid quietly starting build-order item 4 (Maps/routing,
  still planned around Google's Maps MCP server per CLAUDE.md's decision
  log) without a dedicated discussion. Not touched this session.
- The live smoke test used a direct scratch script against `agent_service`
  functions (not a full browser click-through of the chat UI) — sufficient
  to prove the tool-calling wiring and cost-control kill switch work
  end-to-end, but the full UI flow (Google OAuth sign-in → chat →
  tour-guide mode actually surfacing Places-sourced content) wasn't
  separately re-verified this session.
- `find_nearby_places`'s fallback geocoding path (`google_places_client.text_search`)
  is a billed call — only exercised when the free Open-Meteo geocoder
  fails, but worth watching if landmark-level `near` values turn out to be
  the common case rather than the exception; could shift real cost higher
  than the "mostly free geocoding" assumption implies.
