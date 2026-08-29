# 2026-08-29 — Wikipedia context reaches itinerary planning, tour-guide depth raised

**Wikipedia place-context, previously reachable only from conversational
Q&A, now also grounds itinerary generation itself via a third, isolated
tool-calling loop -- and tour-guide-mode replies can come through fuller
now that the detail cap tripled.**

## Changes shipped

- `backend/app/agent_service.py`: new `gather_place_context_for_itinerary(prompt)`
  + `PLANNING_TOOL_CALLING_ENABLED` (default `True`) + `PLANNING_TOOL_SYSTEM_PROMPT`.
  A third, fully isolated tool-calling loop -- own flag, own system prompt,
  own `types.Tool` wrapper (`tools.PLANNING_TOOL_SCHEMAS`) -- so it can never
  be silently exposed or disabled by flipping `AGENT_TOOL_CALLING_ENABLED`
  (currency, still paused) or `QA_TOOL_CALLING_ENABLED` (conversational
  Q&A), matching this module's existing per-feature isolation principle.
  Both place-context loops call the identical `get_place_context` tool
  function underneath; only the loop/flag/prompt differ.
- `backend/app/llm_service.py`: `generate_itinerary()`'s existing
  once-per-conversation concurrent-gather step (previously just
  `gather_trip_context` for currency + `_infer_trip_meta`) now also runs
  `gather_place_context_for_itinerary` concurrently (3 workers instead of
  2), joining whichever of the two tool-loop results are non-empty into
  the same `trip_context` string that already gets folded into the
  chunk-generation prompt and cached as `Conversation.agent_context` --
  **no new DB column, no new caching logic** -- this reuses the exact
  cache slot and mechanism currency already had, since it's a generic
  "extra facts to fold into the prompt" bag, not currency-specific.
- `backend/app/tools.py`: `_DETAILED_CHAR_CAP` raised `2000 -> 6000` for
  `get_place_context(detail="detailed")` -- explicit product decision
  ("raise the cap, keep a ceiling", not remove it entirely) so tour-guide
  replies can come through with real depth (verified live: a 2478-char
  Eiffel Tower extract that would have been truncated at 2000 now comes
  through whole) while a genuinely huge article (a whole country/major
  city) still can't blow the prompt budget on one call.
- Tests: `backend/tests/test_agent_service.py` (+6: disabled short-circuit,
  schema isolation, own system prompt, raw-prompt-no-destination-wrapping,
  network-failure-quiet-fail, brief/error-instruction assertions --
  mirroring the existing currency/QA test patterns exactly), `backend/tests/test_llm_service.py`
  (extended the file's autouse `mock_agent_context` fixture to also mock
  the new function -- avoids a repeat of this project's past "10
  pre-existing tests hit the real Gemini API" incident; extended
  `test_cached_agent_context_skips_the_agent_step_entirely` to assert the
  new call is also skipped when cached; added
  `test_currency_and_place_context_are_combined_when_both_return_findings`
  for the join behavior). Full suite: 222 passed, `ruff check`
  clean (this run already includes the 7 new tests above -- no pre-change
  baseline was captured this session to diff against). No other test file needed changes -- every router-level test that
  touches `new_trip`/`edit_trip` replaces `llm_service.generate_itinerary`
  wholesale rather than letting its internals run, confirmed by direct
  grep before assuming so, per this project's own established discipline
  for this class of change.

## Key learnings

- **Live-verified the new loop is correct and reliable in isolation, but
  intermittently silent when run as the 3rd simultaneous Gemini call.**
  Called directly (`gather_place_context_for_itinerary("5 days in Lisbon, Portugal")`,
  `"...Vienna, Austria"`, `"...Kyoto, Japan"`), it worked every single time
  -- called the tool correctly, got a real Wikipedia-grounded summary
  back. Run as one of three concurrent calls inside
  `generate_itinerary()`'s `ThreadPoolExecutor` (currency loop +
  place-context loop + `_infer_trip_meta`, all firing at once), it
  returned real content in roughly half of ~4 end-to-end trial runs and
  silently `""` the rest of the time -- with `_infer_trip_meta` itself
  occasionally also falling back to `destination="Unknown"` under the same
  concurrent load, a **pre-existing** failure mode (already swallows any
  exception into that fallback, unrelated to this change) that just
  became slightly more visible with a third concurrent request added to
  the mix. This is consistent with this project's already-documented
  free-tier rate-limit sensitivity (see CLAUDE.md's Gemini decision-log
  row) -- not a bug introduced by this session's change, and not
  something a retry loop was added to paper over, since "fails quietly,
  itinerary generation proceeds exactly as before" is this module's
  explicit, deliberate contract for every tool-calling step (currency
  already had this exact same silent-failure shape; place-context
  planning now shares it). Flagging honestly rather than claiming
  rock-solid reliability that wasn't actually observed.
- Instrumenting `_run_tool_loop` directly (temporarily, for this
  diagnostic only) confirmed the isolated calls' tool-call round-trip
  works exactly as designed: `get_place_context({'place_name': 'Vienna'})`
  called, real Wikipedia extract returned, model produces a clean 2-4
  sentence grounding summary from it.
- Confirmed live that the raised `_DETAILED_CHAR_CAP` (2000 -> 6000)
  actually matters, not just in theory: Eiffel Tower's full extract is
  2478 characters -- previously silently truncated, now comes through
  whole. Colosseum (1893) and the tested Belém Tower variant (1336) both
  already fit under the *old* cap, so the increase only changes behavior
  for longer articles, as intended.

## Open items / follow-ups

- The itinerary-planning loop's occasional silent empty result under
  3-way concurrent load is accepted as-is (matches this module's existing
  design contract for every tool step here), not fixed with retries or
  reduced concurrency this session -- revisit only if it turns out to
  happen often enough in real use to matter, not speculatively.
- Per-item/per-day place lookups *during* chunk generation (rather than
  one background-grounding pass before generation starts) remain out of
  scope, same as noted in CLAUDE.md's "Place context" decision row --
  `ItineraryItem` still has no location field to resolve against, and
  chunk generation's `response_schema` structured-output calls don't mix
  cleanly with live function-calling in the same call.
