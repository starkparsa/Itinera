# 2026-08-31 — Tier 2: agent_service logging + the llm_service/agent_service coupling

**Continuation of the same day's architecture-review pass (Tier 0/Tier 1
covered in the previous session doc) — the two remaining Tier 2 findings
that didn't need a product decision.**

## Changes shipped

- **Silent tool-loop failures now logged**: `agent_service._run_tool_loop`
  used to catch every exception and return `""` with zero logging — a real
  gap since all three of its callers (currency, conversational
  place-context, itinerary-planning place-context) are on by default in
  production. Added `loop_name` (a short fixed string per caller:
  `"currency"`, `"qa_place_context"`, `"planning_place_context"`) so a
  `logger.exception(...)` on any failure, and a `logger.warning(...)` on
  hitting `MAX_TOOL_ROUNDS` without a final answer (a different failure
  shape — the model keeps calling tools instead of ever answering), both
  say which loop actually failed. The `""`-to-the-caller contract every
  caller's docstring documents is unchanged — this only adds visibility,
  it doesn't change behavior.
- **Removed the `llm_service.py` <-> `agent_service.py` coupling**: new
  `backend/app/gemini_client.py` now owns Gemini client construction,
  `GEMINI_MODEL`, and the thinking-config — previously `agent_service.py`
  imported `llm_service.py` and reached into its underscore-prefixed
  internals (`llm_service._get_client()`, `llm_service.GEMINI_MODEL`,
  `llm_service._THINKING_CONFIG`) to get the same three things for its own
  tool-calling loops. That reach-across was also this codebase's one
  circular import (`llm_service` imports `agent_service` for the
  itinerary-planning gather step; `agent_service` imported `llm_service`
  right back, for this and only this). `llm_service.py` re-exports
  `GEMINI_MODEL`/`_THINKING_CONFIG`/`_get_client` as aliases onto
  `gemini_client` so the existing test suite's
  `patch("app.llm_service._get_client", ...)` call sites needed zero
  changes; `agent_service.py` no longer imports `llm_service` at all.
  Verified live (not just by reading the diff): a fresh interpreter import
  confirms `agent_service` has no `llm_service` attribute, and both
  `gemini_client.GEMINI_MODEL is llm_service.GEMINI_MODEL` and
  `llm_service._get_client is gemini_client.get_client` hold.

## Key learnings

- The entire `llm_service` dependency inside `agent_service.py` turned out
  to be exactly one function (`_call_gemini_with_tools`) reaching for
  exactly three names — every other mention of `llm_service` in that file
  was a comment/docstring, not code. Worth actually grepping for real
  usages before assuming a shared-module extraction needs to touch more
  than it does.
- Kept the extraction backward-compatible by design (aliases in
  `llm_service.py`, not a rename) specifically to avoid a wide,
  low-value test-mock update — the same shape of "mechanical, not
  logic-changing, but the fallout only shows up in tests" risk this file's
  own CLAUDE.md documents from the `classify_intent` tuple-return change.

## Open items / follow-ups

- Tier 2's third item (sequential per-chunk itinerary generation for long
  trips) deliberately not touched — a real latency/throughput trade-off
  against the existing anti-repetition mechanism, not a bug; revisit only
  if long-trip generation latency becomes an actual complaint (see
  CLAUDE.md's architecture-review entry).
