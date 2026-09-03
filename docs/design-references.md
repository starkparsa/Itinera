# Design references

Pointers to published design artifacts for Itinera — not source of truth for
implemented UI (the code is), but the working references for design
discussion and iteration. All links are private Claude Artifacts/Design
canvases, viewable only by the account that published them.

## Current direction: Trip Hub v2, 2026-09-03

**[Trip Hub Direction](https://claude.ai/code/artifact/3dbae3ae-5bdc-433a-bb84-6f7252cbbeac)**
— the direction to actually build from. Two pages recreating the original
UX Directions canvas's "Trip Hub" concept (below) as standard product UI:

- **Page 1, Your Trips** — sidebar (past/draft/upcoming trips as cards with
  a small real city-photo thumbnail each) + a trip grid on the main panel.
  A draft trip with no dates shows `— not fetched yet —` instead of a
  weather figure — nothing is fabricated ahead of the data existing.
- **Page 2, Trip Hub** — an active trip: chat thread, day-by-day itinerary,
  and a right-hand data column (Weather / Flight / Saved Places) that only
  ever shows a card once that tool has actually returned something.

Styling: Dusk City palette (Direction C, below) carried through as the
actual token values — hue-locked neutrals, no pure grey. Buttons are flat,
small-radius, no gradient fills. Real per-trip city photography (Wikimedia
Commons, CC-licensed, credited) used as small card thumbnails, not a
full-bleed strip.

**Both the trip-list sidebar and the Trip Hub's tools column are collapsed
by default** — nothing extra on screen until the user explicitly asks for
it, consistent with the "nothing pre-printed" principle above. A hamburger
toggle (browser-chrome bar) opens the sidebar; a panel-edge chevron opens
the tools column. Verified via direct DOM checks that all four
open/closed combinations resolve to the correct layout.

**Superseded exploration — "City Passport," 2026-09-03, rejected same day:**
before landing on Trip Hub v2, a "the interface is a boarding-pass /
travel-document, not a dashboard" direction was fully built and iterated
twice — **[City Passport Direction](https://claude.ai/code/artifact/de123984-1e67-4c21-b632-fc224f86bc50)**
(single chat screen) and **[City Passport Full Mockup](https://claude.ai/code/artifact/97e48d8c-bf4a-4561-a0c7-cff2b736600e)**
(website shell + two app screens, including a literal "Passport" tab of
stamped past trips). Explicitly rejected by the user ("forget about city
passport i do not like the idea") in favor of a standard product UI built
from the original UX Directions PDF export instead. Kept here, not deleted,
as the record of what was tried and why it didn't stick — *revisit only if
the travel-document metaphor comes back up explicitly; don't re-propose it
by default.*

## Origin: UX directions (web + app), 2026-09-02 — recolored 2026-09-03 to Dusk City

**[Itinera UX Directions](https://claude.ai/code/artifact/42c85942-3b1a-4f56-8381-9af74ecf5600)**
— editable canvas, 5 artboards across two pages (Website / App). Explores a
"Trip Hub" concept: the itinerary, weather, and (future) flight tracking
become a persistent structured record instead of living only inside chat
scroll, which is how the app works today (see `TripView.tsx`). Includes a
Flight Tracking mockup for the price-tracking feature discussed the same
session (see `decisions.md`'s Flights entry — not built yet).

Originally built from the app's then-live tokens (teal-700 primary, amber
tour-guide accent). **2026-09-03: recolored to Direction C — Dusk City**
(indigo `oklch(0.45 0.11 265)` primary) after the palette direction was
chosen — see the Palette research section below. This canvas's primary
brand color now leads the actual chosen palette rather than the old
teal/amber baseline; the copper tour-guide accent from Direction C is not
yet reflected in this canvas's tour-guide-mode chip styling (still neutral
gray here) — a smaller follow-up if it's worth a second pass. Geist font
and the existing emerald/sky alert convention are unchanged.

Known gaps flagged alongside the mockups (not resolved by them): no user
research behind these directions, no native-vs-PWA decision made for "the
app", feature order follows the documented build order rather than measured
demand, no accessibility pass done yet.

Superseded by **Trip Hub v2** above as the direction to build from — this
canvas is where the "Trip Hub" concept and the Website/App split originated
and stays useful for that context, but its specific mockups (still on the
recolored teal/amber-derived layout, no collapse-by-default behavior) are
no longer the current reference.

## Backend request-flow diagram, 2026-09-02

**[Itinera Request Flow (Editable)](https://claude.ai/code/artifact/6a3cb609-f49f-4e17-a84a-2388befc47ee)**
/ **[read-only version](https://claude.ai/code/artifact/74c3d8e5-acaa-4c04-a47a-37fb042cec08)**
— traces the real branching in `routers/trips.py` → `classify_intent()`'s
four outcomes, the two schema-isolated tool-calling loops in
`agent_service.py`, and the two things that never touch the LLM
(`weather_service.py`, the DB writes). Made to correct a hand-drawn
architecture sketch that had collapsed several of these into one box.

## Palette research, 2026-09-02 — Direction C (Dusk City) chosen 2026-09-03

**[Itinera Palette Directions](https://claude.ai/code/artifact/1141672a-213f-4d34-a1a1-262dc87c3f38)**
— four travel-evocative color directions, each with light/dark swatches and
a live chat-bubble mockup in both normal and tour-guide mode: **A. Ocean &
Golden Hour** (the current teal/amber, refined — the only direction using
the app's real, verified color values), **B. Terracotta & Sage**
(Mediterranean/desert), **C. Dusk City** (indigo + copper streetlight —
**chosen**), **D. Trail & Canyon** (forest green + canyon rust). Every
pairing keeps 97°–150° of hue separation between primary and tour-guide
accent — distinct enough to read as a mode switch, not so far apart it
clashes.

**Direction C's exact values** (first-pass estimates, not yet run through a
formal WCAG contrast checker):
- Primary, light: `oklch(0.45 0.11 265)` / dark: `oklch(0.72 0.16 266)`
- Tour-guide accent, light: `oklch(0.58 0.15 55)` / dark: `oklch(0.80 0.17 62)`
- Assistant tour-guide bubble tint, light: bg `oklch(0.965 0.03 55)`,
  border `oklch(0.87 0.07 55)`, text `oklch(0.32 0.09 55)`; dark: bg
  `oklch(0.32 0.05 62)`, border `oklch(0.48 0.09 62)`, text `oklch(0.9 0.06 62)`

The UX Directions canvas above has been recolored to this primary. Not yet
done: wiring these tokens into `globals.css`, applying the assistant-bubble
tint to `ChatMessage.tsx`, and a real WCAG AA contrast pass.

Real gap found while building this: `ChatMessage.tsx`'s assistant bubble
is always plain `bg-card` — tour-guide mode today only ever recolors the
**user's own** bubble, never the assistant's tour-guide replies. Every
mockup on the page fixes this with a soft, low-chroma tint of the accent
hue on the assistant bubble; not yet applied to the real component.

B/C/D's oklch values are first-pass estimates calibrated to match
teal-700/amber-700's lightness-chroma pattern, not verified Tailwind-named
stops — a real WCAG AA contrast check is needed before any of them ship.
