# 2026-08-27 — Day-count drift and tour-guide misrouting, both live-verified fixed

**Two real bugs found through live use of the site, both traced to root
cause via direct code reads, fixed with grounded prompt changes (not hard
logic), and confirmed live against the real Gemini API.**

## Changes shipped

- `backend/app/llm_service.py`: `_infer_trip_meta`/`generate_itinerary`
  gained a `previous_total_days` parameter — folded into the meta-inference
  prompt as a soft fact ("this conversation already has an N-day itinerary,
  keep it unless the request explicitly asks for a different length")
  rather than a hard override, so day count stays changeable by text alone.
- `backend/app/routers/trips.py`: the `previous_trip` lookup (previously
  only used for the `start_date` fallback) is now hoisted earlier and
  reused to compute `previous_total_days` (`max(item.day_number)` over the
  previous trip's saved items) and pass it into `generate_itinerary`.
- `backend/app/llm_service.py`: `INTENT_INSTRUCTIONS` (the `classify_intent`
  prompt) gained concrete inline examples distinguishing `edit_trip`
  (explicit itinerary-modification requests) from `question` (conversational/
  tour-guide-style phrasing, including "be my tour guide"/"take me through
  this place" — reused verbatim from `agent_service.py`'s
  `QA_TOOL_SYSTEM_PROMPT` to keep the two prompts consistent).
- 5 new tests across `backend/tests/test_llm_service.py` and
  `backend/tests/test_trips_router.py`; 1 existing test
  (`test_generate_trip_forwards_requested_days_to_llm_service`) updated for
  the new kwarg. Full suite: 208 passed.

## Bugs found & fixed

- **Symptom**: "Plan a 5 day trip to Miami" → real 5-day itinerary → "I
  want to experience the artsy miami" (no day-count language) → silently
  became a 3-day itinerary. **Root cause**: `_infer_trip_meta` re-guessed
  `total_days` from scratch via Gemini on every call, new or edit turn
  alike, with nothing anchoring it to an already-established day count —
  unlike `Trip.start_date`, which already had a "reuse the previous trip's
  value" fallback. **Fix**: ground the meta prompt in the real previous day
  count as a soft, overridable fact. **Live-verified**: reproduced the
  exact scenario, day count now stays at 5; also verified an explicit
  change ("make it a full week instead") still moves it to 7, proving the
  fix didn't accidentally hard-lock length.
- **Symptom**: with a Little Haiti itinerary already in the conversation,
  "i think i am already in little haiti can you be my tour guide and take
  me through this place" produced a brand-new 3-day itinerary instead of a
  conversational answer. **Root cause**: `classify_intent`'s prompt had
  zero few-shot examples, so nothing disambiguated narrative/tour-guide
  phrasing from an actual itinerary-modification request — it was
  classified `edit_trip`/`new_trip` instead of `question`, so
  `agent_service.answer_question_with_tools`/`get_place_context` (added
  the day before, see `2026-08-27-wikipedia-place-context-tool.md`) never
  even ran. **Confirmed the Q&A tool path itself was already correct** —
  both `QA_TOOL_SYSTEM_PROMPT` and the tool's schema description already
  explicitly instruct `detail="detailed"` for "be my tour guide" phrasing.
  **User's own hypothesis (split the Wikipedia tool into two) was
  evaluated and correctly rejected** — it would not have fixed this, since
  the message never reached the tool-calling loop at all; the fix belongs
  entirely in `classify_intent`'s prompt. **Live-verified**: reproduced the
  exact scenario, now correctly routes to `question` (no new `trip_id`, a
  real conversational reply); also verified a genuine edit request ("swap
  day 2 for something more food-focused") still correctly regenerates the
  itinerary, proving the tightened wording didn't over-correct.

## Key learnings

- Both bugs share a shape worth remembering: a new capability
  (`previous_trip` reuse for `start_date`; `get_place_context`'s
  tour-guide `detail` mode) was added and worked correctly in isolation,
  but a *sibling* code path (`_infer_trip_meta`'s day-count inference;
  `classify_intent`'s routing) wasn't updated to match, so the new
  capability was silently unreachable/undermined from certain angles. Worth
  a habit: when adding a capability that depends on correct upstream
  routing or a correct upstream default, explicitly check the sibling
  logic that was already solving an analogous problem (here, `start_date`'s
  existing fallback pattern was the direct template for the day-count fix).
- `classify_intent`'s tests are 100% mocked at `_call_gemini` — this gives
  zero real coverage of prompt-quality regressions. The regression-guard
  unit tests added here (substring assertions on `INTENT_INSTRUCTIONS`)
  can only prove the examples aren't accidentally deleted later, not that
  real classification behavior is correct — that needs a live pass every
  time the prompt changes, same as this project's other prompt-tuning fixes.
- Live-verified but not fixed this session, flagged for awareness: the
  tour-guide reply for Little Haiti (scenario 3 below) included quite
  specific place names (a "Little Haiti Museum", specific street
  addresses) that read as plausible general-knowledge fill rather than
  strictly Wikipedia-grounded facts — `get_place_context` may not always
  get called even when it should, or its result may get blended with the
  model's own guesses in the final narration. Not the two bugs this
  session targeted; worth a closer look separately if fabricated-sounding
  specifics in tour-guide answers turn out to be a real recurring problem.

## Follow-up, same day: tour-guide fabrication investigated and fixed

Instrumented `agent_service.answer_question_with_tools` directly (wrapped
`tools.get_place_context` to log every call + raw result) and replayed the
Little Haiti scenario ~9 times, including once with the full rich
conversation history from the original report (artsy Miami → Vizcaya →
galleries → tour guide). Findings:

- `get_place_context` was reliably called every time (sometimes retried
  once or twice — the model tried `"Little Haiti, Miami"` first, which
  doesn't resolve on Wikipedia, before correctly falling back to
  `"Little Haiti"` alone) and returned real, correct grounding (the actual
  Toussaint L'Ouverture statue, "Lemon City" history).
- The *original* transcript's fabricated-looking itinerary
  ("Naomi's Garden", "Chef Creole" etc., in a Day 1/2/3 format) was
  actually the pre-fix **misrouting bug** (already fixed above), not a
  separate fabrication bug — that reply never went through the Q&A/tool
  path at all.
- The fabrication-adjacent behavior *was* real, but only showed up in this
  session's own verification run of the misrouting fix (the earlier
  "Naomi's Garden"/"Chef Creole" reply from scenario 3) — root cause: in
  `detail="detailed"` mode, `QA_TOOL_SYSTEM_PROMPT` correctly said "don't
  invent when the tool errors" but had no guardrail against inventing
  *additional* specific business names/addresses on top of a
  *successful* tool result, and the "give a fuller answer" instruction for
  detailed mode implicitly invited that kind of embellishment.

**Fix**: added an explicit instruction to `QA_TOOL_SYSTEM_PROMPT` — only
name a specific business/venue/address if it came from the tool result or
was already mentioned in the conversation; describe the kind of experience
instead of naming an unverified venue. **Live-verified**: reran the same
rich-context scenario 4 more times post-fix — all four stayed grounded in
real facts (the statue, "Lemon City", the conversation's own already-named
"Little Haiti Cultural Complex") with no invented venue names, consistently
using generic phrasing ("a local spot", "neighborhood cultural hubs")
instead. New regression-guard test:
`test_qa_system_prompt_instructs_against_inventing_specific_venues_in_detailed_mode`.

## Open items / follow-ups

- LLM output is non-deterministic — this fix reduces the likelihood of
  invented venue names but can't guarantee zero occurrences. Worth a
  periodic live spot-check if it recurs, same as any other prompt-tuning
  guardrail in this codebase.
