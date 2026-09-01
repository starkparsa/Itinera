# 2026-09-01 — Intent misclassification: recommendation asks and physically-present tour-guide triggers

**A real user-reported conversation showed two `classify_intent` gaps: a physically-present narrative request didn't trigger persistent tour-guide mode, and a single-place recommendation ask got misclassified as `new_trip`, regenerating a whole unrelated 5-day itinerary instead of staying conversational.**

## Changes shipped

- [`backend/app/llm_service.py`](../../backend/app/llm_service.py) —
  `INTENT_INSTRUCTIONS` extended with:
  1. A `tour_guide_requested` trigger example for phrasing like "I'm at X
     and I want to understand its importance" (physically-present
     narrative/deep-dive requests), not just the literal "be my tour
     guide"/"take me through this place" set.
  2. An explicit `question` vs. `new_trip` disambiguation: a request to
     recommend or suggest ONE specific place/activity (e.g. "suggest a
     place where I can read but still see the murals") is `question`, even
     when phrased with travel-adjacent words like "go somewhere" — not a
     request to plan a new trip.
- Regression tests added to `test_llm_service.py` (string-presence guards
  on `INTENT_INSTRUCTIONS`, same pattern as the existing tour-guide-vs-
  edit_trip regression test — real classification behavior needs live
  verification, mocked tests can't prove it).

## Bugs found & fixed

- **Symptom (user-reported, real conversation)**: A user said "I think i
  am already at wynwood walls i really want understand the importaance of
  the place" — got a good Wikipedia-grounded answer, but persistent
  tour-guide mode never activated (no "Tour guide mode on." prefix, and
  the mode didn't persist). Two turns later, "That is great i want to go
  somewhere to read a book can you suggest a place where i can go but
  still see the murals" — a request to recommend one nearby spot — was
  misclassified as `new_trip` and generated a brand-new, unrelated 5-day
  Miami itinerary starting with "Arrive in Miami and check into your
  hotel," ignoring that the user had just said they were already at
  Wynwood.
- **Root cause**: `INTENT_INSTRUCTIONS`'s `tour_guide_requested` trigger
  list only recognized the literal "be my tour guide"/"take me through
  this place" phrasing, not a physically-present narrative request in
  different words. Separately, the `new_trip` bullet had no guard against
  a message that merely contains travel-adjacent words ("go somewhere")
  while actually asking for a single recommendation, not a new trip — the
  same failure *shape* as the already-documented 2026-08-27 bug
  (`docs/sessions/2026-08-27-day-count-drift-and-tour-guide-misrouting.md`),
  recurring on a new, uncovered phrasing variant.
- **Fix**: extended `INTENT_INSTRUCTIONS` with concrete examples for both
  gaps (prompt engineering, not hard logic — same discipline the
  2026-08-27 fix used and CLAUDE.md documents as the right lever here).
- **Live-verified against the real Gemini API using the exact reported
  transcript**:
  - `classify_intent(msg1, "")` → `("question", True)` (was `False`
    before the fix).
  - `classify_intent(msg4, conversation_context)` → `("question", False)`
    (was effectively `new_trip`/`edit_trip` before the fix, based on the
    observed full-itinerary-regeneration behavior).
  - Full `answer_question_with_tools` call for msg4 (with
    `tour_guide_mode=True`, as msg1 would now set) returned a real,
    grounded recommendation naming actual nearby cafés (maman, Pura Vida)
    — not a regenerated itinerary.
  - **Over-correction check**: confirmed a genuine new-trip request ("I
    want to go somewhere completely different next -- plan me a week in
    Tokyo") still correctly classifies `new_trip`, an explicit edit
    ("make it a week instead") still `edit_trip`, and an explicit tour-guide
    request still sets `tour_guide_requested=True` — the broadened
    instructions didn't swallow the cases they weren't meant to change.

## Key learnings

- This is the same failure *category* CLAUDE.md's decision log already
  names ("bug/correctness pass," Fourth round) — `classify_intent` having
  zero or narrow few-shot examples for a given phrasing shape is a
  recurring source of real, user-visible misrouting bugs, not a one-time
  fix. Worth treating any future report of "it regenerated my itinerary
  when I didn't ask it to" as this same category first.
- The new `find_nearby_places`/`get_place_details` tools (shipped earlier
  today) made the *correct* answer for msg4 immediately available once
  classification was fixed — the tool-calling side was already right, the
  bug was entirely upstream in the routing gate. A reminder that principle
  #1 ("classify before anything expensive runs") means a classification
  bug can make even a perfectly working downstream feature invisible.

## Open items / follow-ups

- None — both fixes verified live end-to-end, full suite passes, no
  over-correction found.
