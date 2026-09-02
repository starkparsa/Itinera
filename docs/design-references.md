# Design references

Pointers to published design artifacts for Itinera — not source of truth for
implemented UI (the code is), but the working references for design
discussion and iteration. All links are private Claude Artifacts/Design
canvases, viewable only by the account that published them.

## UX directions (web + app), 2026-09-02

**[Itinera UX Directions](https://claude.ai/code/artifact/42c85942-3b1a-4f56-8381-9af74ecf5600)**
— editable canvas, 5 artboards across two pages (Website / App). Explores a
"Trip Hub" concept: the itinerary, weather, and (future) flight tracking
become a persistent structured record instead of living only inside chat
scroll, which is how the app works today (see `TripView.tsx`). Includes a
Flight Tracking mockup for the price-tracking feature discussed the same
session (see `decisions.md`'s Flights entry — not built yet). Built from the
app's real tokens: teal-700 primary (`globals.css`), the amber tour-guide
accent, Geist font, the existing emerald/sky alert convention.

Known gaps flagged alongside the mockups (not resolved by them): no user
research behind these directions, no native-vs-PWA decision made for "the
app", feature order follows the documented build order rather than measured
demand, no accessibility pass done yet.

## Backend request-flow diagram, 2026-09-02

**[Itinera Request Flow (Editable)](https://claude.ai/code/artifact/6a3cb609-f49f-4e17-a84a-2388befc47ee)**
/ **[read-only version](https://claude.ai/code/artifact/74c3d8e5-acaa-4c04-a47a-37fb042cec08)**
— traces the real branching in `routers/trips.py` → `classify_intent()`'s
four outcomes, the two schema-isolated tool-calling loops in
`agent_service.py`, and the two things that never touch the LLM
(`weather_service.py`, the DB writes). Made to correct a hand-drawn
architecture sketch that had collapsed several of these into one box.
