# 2026-08-26 — Q&A date-resolution bug (round 3) + currency paused

**A third, distinct weather/Q&A grounding bug was found and fixed live, a
follow-up audit checked for the same pattern elsewhere, and currency
conversion was paused again — this time by product decision, not a
reliability problem.**

## Changes shipped

- `routers/trips.py`'s `question` branch now tries
  `date_resolver.resolve_trip_start_date(request.prompt, date.today())` on
  the question's own text when `latest_trip.start_date is None`, and
  persists the resolved date onto the trip if one resolves — see CLAUDE.md's
  decision log and bug-pass history for the full rationale.
- Two new regression tests in `backend/tests/test_trips_router.py`:
  `test_question_resolves_start_date_from_the_question_itself_when_trip_has_none`
  and `test_question_does_not_override_an_already_resolved_start_date`.
- `agent_service.AGENT_TOOL_CALLING_ENABLED` flipped back to `False` — currency
  conversion paused again via the existing kill switch. No other code
  changed; `gather_trip_context()` already short-circuits to `""` when this
  flag is off.

## Bugs found & fixed

- **Symptom** (exact reported text): a trip generated from "Build me a 5 day
  trip to austin" (no date phrase), then asked "what do the temperatures
  look like if i want to go there this weekend" twice, both times got "I
  don't have current weather data to tell you..." even though "this
  weekend" is a phrase `date_resolver.py` already recognizes.
- **Root cause**: `Trip.start_date` was correctly `None` (the generating
  prompt never named a date), but `routers/trips.py`'s `question` branch
  never called `date_resolver` at all — on any phrasing — it only ever read
  the trip's already-resolved (here, null) `start_date`. This is a third,
  structurally distinct bug from the two earlier weather/Q&A rounds (see
  CLAUDE.md): round one was real weather data existing but never being
  passed to `answer_question`; round two was `date_resolver`'s regex not
  recognizing "N days from now" phrasing at *generation* time. Neither
  touched the Q&A branch's total absence of any date-resolution call.
- **Fix**: see "Changes shipped" above. Verified live against the exact
  reported prompt pattern (a no-date-phrase generation + a "this weekend"
  follow-up) after redeploying the local Docker stack.

## Key learnings

- Three bugs in a row can produce an identical user-visible symptom ("I
  don't have weather data") while being three genuinely different code
  defects. Recognizing that mattered here: a naive "wasn't this already
  fixed?" reaction would have led to re-checking the *previous* fixes
  instead of noticing the *new* code path (Q&A) had never had this logic at
  all.
- A follow-up audit for the same divergence shape ("generation-time-only
  logic missing from the question-answering path") across the rest of the
  codebase found:
  - **Currency's `Conversation.agent_context` gate** caches "found nothing"
    per-conversation forever, so a later question that plainly needs a
    fresh currency figure never gets one — a real instance of the same
    pattern, but a documented, deliberate cost-control tradeoff (avoiding a
    Gemini call every question turn), not an oversight. Now moot: currency
    itself is paused (see below).
  - **Weather always geocodes `trip.destination`**, never a different city
    named in a follow-up question — a real, still-open gap. Unlike the date
    fix, there's no existing deterministic extractor to reuse for
    destination the way `date_resolver.py` was reused for dates.
  - `llm_service._infer_trip_meta` (destination/day-count inference) being
    generation-only is correctly scoped, not a gap — a question turn never
    needs a freshly-inferred destination or day count.

## Open items / follow-ups

- Weather destination-override (a follow-up question naming a different
  city than the trip's) is a known, real gap — not fixed this session.
  Closing it needs either a new lightweight deterministic extractor or a
  dedicated LLM call, not a drop-in reuse of `date_resolver.py`.
- Currency's cache-once-per-conversation gate has the same shape of gap as
  the date bug, but is moot for now since currency conversion itself is
  paused (`AGENT_TOOL_CALLING_ENABLED = False`, product decision, not a
  reliability finding — distinct from weather's outright removal). Worth
  remembering if currency is ever re-enabled.
