# 2026-09-01 — Conversation-context truncation dropped the most recent turn

**A real user-reported conversation showed "can we add to the plan" (after discussing scuba diving) regenerated an itinerary with zero mention of diving — `_build_conversation_context`'s char-budget truncation was slicing from the head of the joined string, silently dropping the newest, most relevant turn instead of the oldest.**

## Changes shipped

- [`backend/app/routers/trips.py`](../../backend/app/routers/trips.py) —
  `_build_conversation_context` rewritten to build from the most recent
  message backward, dropping the *oldest* of the last `MAX_CONTEXT_MESSAGES`
  turns first when the char budget (`MAX_CONTEXT_CHARS`) is tight, instead
  of slicing the chronologically-joined string with `[:MAX_CONTEXT_CHARS]`
  (which kept the oldest content and dropped the newest). Order in the
  returned string stays chronological (oldest-kept-first) — only *which*
  messages survive the budget changed.
- New tests in `test_trips_router.py`: direct unit tests for
  `_build_conversation_context` (keeps-most-recent-over-budget,
  preserves-chronological-order, under-budget-keeps-everything).

## Bugs found & fixed

- **Symptom (user-reported, real conversation)**: after a Q&A turn
  correctly answered "where else can i go to in miami if i like scuba
  diving" with real grounded content (Florida Keys, Florida Reef Tract,
  Biscayne National Park), the user said "can we add to the plan." The
  regenerated 5-day itinerary that came back had **zero mention of diving,
  Florida Keys, or Biscayne** anywhere — just a re-shuffled version of the
  same reading/Wynwood-themed itinerary from before the scuba question was
  ever asked.
- **Root cause**: `_build_conversation_context` joined the last
  `MAX_CONTEXT_MESSAGES` (6) messages in chronological order, then applied
  `[:MAX_CONTEXT_CHARS]` (1000) to the joined string. Reproduced exactly:
  with the actual message lengths from this conversation, the 1000-char
  cutoff landed mid-sentence through the scuba diving answer, keeping only
  the *earlier* turns (Wynwood cultural-significance discussion) and
  losing the newest one (the actual content "add to the plan" referred
  to) entirely. This string feeds directly into `llm_service.generate_itinerary`'s
  `conversation_context` parameter for the `edit_trip` branch (`routers/trips.py`
  itself documents that edit_trip "regenerates the whole thing with
  conversation_context carrying the requested change") — so the model
  regenerating the itinerary had no way to know what to add.
- **Fix**: iterate the last 6 messages newest-to-oldest, accumulate into
  the char budget, and stop (dropping only the oldest) once the budget
  would be exceeded — then reverse back to chronological order for the
  final string. The most recent turn is now always preserved, since a
  follow-up like "add to the plan" or "can we add to the plan" always
  refers to what was *just* discussed.
- **Live-verified with the exact reported message content**: reproduced
  the bug first (confirmed the pre-fix truncation lands mid-sentence
  through the scuba answer, dropping every relevant keyword), then
  confirmed the fix preserves "scuba diving," "Florida Keys," and
  "Biscayne" intact. Ran the *actual* `generate_itinerary` call with the
  fixed context string against real Gemini: the resulting itinerary now
  includes a real day trip to the Florida Keys/Florida Reef Tract and a
  day at Biscayne National Park for diving/snorkeling — exactly what the
  user asked to add.

## Key learnings

- This bug shares a root-cause *shape* with several bugs already in
  CLAUDE.md's "bug/correctness pass" history (data that exists somewhere
  in the system but doesn't reach the step that needs it) — but this one
  is a genuinely different mechanism (a truncation direction bug, not a
  missing grounding call or a classification miss). Worth remembering as
  its own category: any fixed-size context/history budget in this
  codebase should be checked for which end it trims from, not just
  whether it exists.
- `_build_conversation_context` is shared by both `classify_intent` and
  itinerary generation (`generate_itinerary`'s `conversation_context`
  param) — this fix benefits both call sites, not just the edit_trip path
  where the bug was first observed. Worth checking intent classification
  quality on long conversations too, since it was reading the same
  truncated (and previously backwards) string.

## Open items / follow-ups

- None — fix verified live end-to-end (both the raw truncation behavior
  and the full itinerary-regeneration output), full suite passes, no
  behavior change for conversations that fit within the char budget
  (verified via the under-budget unit test).
