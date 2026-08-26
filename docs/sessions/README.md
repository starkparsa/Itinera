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
| [2026-08-26](2026-08-26-qa-date-bug-and-currency-pause.md) | Third weather/Q&A grounding bug fixed (question text's own date phrase never resolved); audit for the same pattern elsewhere; currency conversion paused again (product decision, not reliability) | Weather destination-override left open as a known gap — no existing extractor to reuse. |
| [2026-08-26](2026-08-26-ics-calendar-export.md) | .ics calendar export for generated itineraries (build-order item 3) | PDF export still deferred. Export control hidden entirely in the UI until a trip has a resolved start date. Not live-verified against a running stack (would cost real Gemini quota) — verified via the automated test suite only. |
| [2026-08-25](2026-08-25-weather-feature-and-llm-reliability.md) | Real per-day weather (Open-Meteo), re-enabled the currency agent step, adopted MCP for future tools, escaped Gemini's 20-req/day free-tier wall with a model swap + Groq fallback | Two live bugs found and fixed post-ship: Q&A fabricating temperatures, and a missed "N days from now" date phrasing. Gemma 4 evaluated and rejected as a Gemini replacement (real structured-output + instruction-following bugs found live). |
