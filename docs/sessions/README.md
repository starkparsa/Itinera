# Session log

A chronological record of what changed each work session and why — the
history `CLAUDE.md` deliberately doesn't keep (it's a snapshot of current
state and decisions, not a timeline). Use this to catch up on what
happened since you were last in this codebase, or to look back at *why*
something was built a certain way and what was learned building it.

**This complements `CLAUDE.md`, it doesn't replace it.** For current
architecture, active decisions, and the build order, `CLAUDE.md` (repo
root) is still the single source of truth — entries here link to it
rather than repeating its rationale.

## How to add an entry

1. Copy `TEMPLATE.md` to `YYYY-MM-DD-short-slug.md` (one file per session,
   or per distinct chunk of work within a long session).
2. Fill it in as you go, or at the end of the session — whichever is more
   accurate. Keep it to what changed, what broke, and what was learned;
   don't transcribe the conversation.
3. Add one row to the table below, newest at the top.

## Sessions

| Date | Summary | Notes |
|---|---|---|
| [2026-08-27](2026-08-27-persistent-tour-guide-mode.md) | New persistent `Conversation.tour_guide_mode` — once triggered, later Q&A follow-ups stay in fuller narrative-guide style until the user explicitly returns to itinerary planning | `classify_intent` extended with a `tour_guide_requested` field (same Gemini call, no extra cost). 28 test mocks across 4 files updated for the new tuple return. Live-verified all 5 scenarios including an adversarial combined-signal case. |
| [2026-08-27](2026-08-27-day-count-drift-and-tour-guide-misrouting.md) | Two live bugs fixed: itinerary day count silently drifting on vague edit turns, and "be my tour guide" phrasing misrouted to itinerary regeneration instead of the Q&A path | Both root-caused via direct code reads, fixed with grounded prompt changes (not hard logic), and live-verified against real Gemini calls, including that neither fix over-corrected (explicit day-count changes and explicit edit requests both still work). |
| [2026-08-27](2026-08-27-wikipedia-place-context-tool.md) | New Wikipedia-grounded `get_place_context` LLM tool for conversational Q&A, via a new tool-calling loop kept fully separate from the paused currency one | Scoped down from a fully-researched-but-deferred Google Maps integration. Live-verified: brief-vs-detailed and fresh-per-turn behavior both confirmed working; a real prompt-tuning bug (model padding "brief" replies with its own knowledge) found and fixed live. |
| [2026-08-26](2026-08-26-codebase-cleanup.md) | Full dead-code/build-hygiene pass across backend + frontend after the OAuth work | **Critical fix**: `frontend/src/lib/` (6 files -- Server Actions, JWT bridge, shared types) had never been in git since the initial commit, silently swallowed by a too-broad `.gitignore` pattern; fixed and files added to tracking. Also removed one dead frontend function, added a missing `backend/.dockerignore` (261MB → 772B build context), split test-only deps into `requirements-dev.txt`. Kept two looks-unreachable-but-intentional capabilities (`.ics` export, calendar-status) after checking with the user. |
| [2026-08-26](2026-08-26-oauth-phase-d.md) | Google OAuth Phase D: Calendar push via `googleapiclient` (MCP go/no-go said no); same-day follow-up merged export into one "Export Plan" button with Calendar consent bundled into login | Caught and fixed a real bug in alembic/env.py that would have dropped every table. Real OAuth credentials verified live up to Google's actual consent screen. |
| [2026-08-26](2026-08-26-oauth-phase-c.md) | Google OAuth Phase C: real per-user data isolation, `TripRequest.user_id` fully removed | 6 new cross-user isolation tests. Phase D (Calendar push) next. Real login still needs a human-created Google OAuth client. |
| [2026-08-26](2026-08-26-oauth-phase-b.md) | Google OAuth Phase B: Auth.js login + JWT bridge to FastAPI, `User.google_sub`, Alembic introduced | Verified live up to Google's real consent screen (rejected placeholder credentials as expected). Real `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` needed to complete login. Phase C (ownership checks) not started. |
| [2026-08-26](2026-08-26-nextjs-migration-phase-a.md) | Streamlit → Next.js migration, Phase A of the Google OAuth + Calendar plan: full UI parity, no auth yet | Phases B (Auth.js login), C (ownership-check retrofit), D (Calendar MCP push) designed but not started — see CLAUDE.md decision log. |
| [2026-08-26](2026-08-26-qa-date-bug-and-currency-pause.md) | Third weather/Q&A grounding bug fixed (question text's own date phrase never resolved); audit for the same pattern elsewhere; currency conversion paused again (product decision, not reliability) | Weather destination-override left open as a known gap — no existing extractor to reuse. |
| [2026-08-26](2026-08-26-ics-calendar-export.md) | .ics calendar export for generated itineraries (build-order item 3) | PDF export still deferred. Export control hidden entirely in the UI until a trip has a resolved start date. Not live-verified against a running stack (would cost real Gemini quota) — verified via the automated test suite only. |
| [2026-08-25](2026-08-25-weather-feature-and-llm-reliability.md) | Real per-day weather (Open-Meteo), re-enabled the currency agent step, adopted MCP for future tools, escaped Gemini's 20-req/day free-tier wall with a model swap + Groq fallback | Two live bugs found and fixed post-ship: Q&A fabricating temperatures, and a missed "N days from now" date phrasing. Gemma 4 evaluated and rejected as a Gemini replacement (real structured-output + instruction-following bugs found live). |
