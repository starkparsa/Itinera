# 2026-08-27 — Wikipedia place-context tool

**Added a new LLM-callable tool (`get_place_context`) that grounds
conversational answers about named places in real Wikipedia data, reached
through a new, separate tool-calling loop — scoped down from a broader
Google Maps integration researched earlier the same session, see
CLAUDE.md's decision log.**

## Changes shipped

- New `backend/app/clients/` package (first module) — `wikipedia_client.py`
  wraps Wikipedia's opensearch/summary/full-extract endpoints, no key, no
  billing, `functools.lru_cache`-cached, proper `User-Agent` header per
  Wikimedia's etiquette policy.
- `backend/app/tools.py`: new `get_place_context(place_name, near=None,
  detail="brief")` tool — brief (default, ~320 chars) or detailed (capped
  2000 chars) Wikipedia-grounded overview, `{"error": ...}` on a miss, same
  convention as `convert_currency`.
- `backend/app/tools.py`: split `TOOL_SCHEMAS` into per-loop subsets
  (`CURRENCY_TOOL_SCHEMAS`, `QA_TOOL_SCHEMAS`) — see "Key learnings" below
  for why this was necessary, not just tidiness.
- `backend/app/agent_service.py`: new `answer_question_with_tools()` +
  `QA_TOOL_CALLING_ENABLED` (default `True`), a second tool-calling loop
  fully independent of `gather_trip_context`/`AGENT_TOOL_CALLING_ENABLED`
  (currency, still paused). Shared round-trip mechanics factored into
  `_run_tool_loop()`.
- `backend/app/routers/trips.py`: the `question` intent branch tries
  `answer_question_with_tools` first, falls back to the existing
  `llm_service.answer_question` when it returns `""` (disabled, or any
  internal failure).

## Bugs found & fixed

- **Test-suite regression, caught before it shipped**: adding the new call
  to the `question` branch meant every existing question-path test in
  `test_trips_router.py` started hitting a real, unmocked Gemini API call
  (this repo's local `.env` has a live `GEMINI_API_KEY`) — test run went
  from instant/mocked to real network calls. Fixed with a file-scoped
  autouse fixture (`mock_qa_tools_by_default` in `test_trips_router.py`)
  defaulting the new function to `""`. **First attempt at this fix was
  itself wrong**: putting the same fixture in `conftest.py` as
  session-wide `autouse=True` broke `test_agent_service.py`'s own direct
  tests of the real function, because `app.routers.trips.agent_service` and
  `app.agent_service` are the same module object — a global monkeypatch on
  one clobbers the other. Moved the fixture into `test_trips_router.py`
  only.
- **Live-verification finding**: the model's final reply after a `"brief"`
  tool call was noticeably longer than the tool's own ~320-char summary —
  it was padding the grounded fact with its own pretrained knowledge
  (dates, side facts) rather than staying proportionately brief, working
  against the user's explicit "don't give a full synopsis by default"
  requirement. Constraining the *tool's* output length wasn't enough;
  fixed by adding an explicit instruction to `QA_TOOL_SYSTEM_PROMPT` to
  match reply length to the detail level used, re-verified live
  (Louvre "brief" dropped from 4 paragraphs to 3 sentences; a later
  "detailed" request and a fresh place's "brief" default both still
  behaved correctly).

## Key learnings

- **A single shared `TOOL_SCHEMAS`/one flag doesn't work once there are
  two independently-gated tool-calling loops.** Originally planned to just
  add the new tool to the existing `tools.TOOL_SCHEMAS` list. Caught during
  design (not live): `gather_trip_context` (currency, paused) and the new
  place-context loop need different kill switches AND different caching
  behavior in the caller (currency: cache once per conversation forever;
  place-context: must run fresh every question turn, since a different
  place can be asked about each time). If both tools were advertised via
  one shared schema, flipping the new loop's flag on would make currency
  reachable again too, silently undoing its pause. Fixed by giving each
  loop its own `types.Tool` schema (`CURRENCY_TOOL_SCHEMAS`/
  `QA_TOOL_SCHEMAS`) — `TOOL_SCHEMAS` (the combined list) is kept only for
  tests/introspection, never passed into a live `GenerateContentConfig`.
- Wikipedia's `action=parse&prop=sections` is deprecated in favor of
  `prop=tocdata` (confirmed live via the API's own deprecation warning in
  the response) — not used in the shipped code (the "Get around"/Wikivoyage
  section-fetch spike from the earlier, now-deferred Maps design), but
  worth remembering if that gets picked back up.
- `action=opensearch` resolves a clean query well ("louvre" → "Louvre" as
  the #1 hit) but a genuine typo can surface the right page below the top
  result ("eiffel towerr" placed "Eiffel Tower" 2nd) — same known-gap
  category this project already documents for `weather_service`'s
  geocoder having no fuzzy-match fallback. Not solved, not worth it without
  a real reported case.
- Gemini's SDK prints a benign stderr warning ("Direct use of automatic
  function calling (AFC) in Models.generate_content is not recommended...")
  on every manual tool-calling call, regardless of
  `automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)`
  already being set correctly — cosmetic, not a real issue, but worth
  knowing it's expected noise, not a sign something's misconfigured.

## Open items / follow-ups

- The broader Google Maps integration (distance/directions/Places API/
  billing setup) was fully researched and designed this session, then
  explicitly deferred by the user in favor of this narrower Wikipedia-only
  piece. The full design (client/tool structure, `clients/`+`tools/`
  package restructuring, prerequisites checklist) is not preserved in a
  committed file — only in this session's conversation — revisit by
  re-deriving from CLAUDE.md's Maps decision-log row plus fresh research
  if/when that work resumes, don't assume the earlier design is still
  fully current.
- `get_place_context` is Q&A-only, not wired into itinerary generation —
  deliberate scope cut (would need per-item place resolution;
  `ItineraryItem` has no location field today).
