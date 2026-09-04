# Progress — Itinera

Dated diary: what happened, what changed, what should happen next.
Consolidated 2026-09-02 from what had been ~21 individual files under
`docs/sessions/`. Newest first. For the decisions this history produced,
see [`decisions.md`](decisions.md); for where things stand right now, see
[`STATUS.md`](STATUS.md).

## 2026-09-04 — Real WCAG AA contrast check, second accessibility pass

Follow-on to the four-group UI/UX review (below), same day: closed out
the two items that review had explicitly left open — a real contrast
check on the Dusk City palette, and a deeper accessibility pass. PR #27.

**Contrast check.** Wrote a small script computing actual oklch->sRGB
relative luminance and WCAG contrast ratios (Björn Ottosson's reference
OKLab/OKLCH matrices) rather than eyeballing hex previews, and ran it
against every text/background and UI-component pair in `globals.css` —
light+dark × normal+tour-guide, ~20 pairs. Found two real AA failures,
both in light-mode tour-guide mode: white button text on the copper
`--primary` only reached 4.31:1 (needs 4.5:1), and the tour-guide badge
similarly at 4.13:1. Before picking a fix, checked whether the problem
was "wrong text color" or "accent itself un-hostable" — tested the app's
own dark `--foreground` text against the same copper too, and it only
reached 4.40:1, also failing. The accent (`oklch(0.58 0.15 55)`) was
simply too mid-toned in either direction. Fixed by darkening it to
`oklch(0.45 0.15 55)`, matching the base indigo's own light-mode
lightness exactly — now 7.47:1 / 7.15:1, and every other pair checked
already passed.

**Second accessibility pass.** A manual POUR pass over the components
that hadn't had one yet turned up the same underlying shape five times:
state conveyed only visually, with no programmatic equivalent. Chat
message speaker (position/color only → added an `sr-only` prefix), the
active sidebar conversation (color only → `aria-current`), the calendar
export result (visible text only → `role="status"`/`"alert"`), the
composer's accessible name (placeholder only, not a reliable label →
`aria-label`), and the conversation-loading skeleton (correctly
`aria-hidden`, but that meant total screen-reader silence during a load
→ a sibling `sr-only role="status"` announcement).

Verified: `tsc --noEmit`, `eslint`, and a full `next build` all clean;
dev server loads with no console/server errors. Shipped as one commit,
one PR (#27, merged via a merge commit, branch deleted after).

## 2026-09-04 — Frontend UI/UX review, worked through in four groups

The user asked for a UI/UX review of the frontend and anything left
behind, then worked through the findings in four scoped groups over one
session, re-reading the current state before each group since the repo
kept moving underneath the plan (Trip Hub v2 and three layout fixes
landed mid-session — see the entries below this one). Two PRs: #24 (the
code) and #25 (this documentation).

**Group A — small, independent fixes.** Sidebar chat deletion now
confirms via a real `AlertDialog` instead of deleting on the first click.
Tour-guide mode gets a visible badge, not just a color shift. `layout.tsx`
gained OpenGraph metadata and a themed viewport/theme-color (the favicon
set turned out to already exist via Next's file convention — checked
before adding a redundant one). First accessibility pass: `aria-live`/
`role=log` on the message transcript, a skip link, focus returning to the
composer after a send, `#main-content` landmarks.

**Real bug caught mid-group: the shadcn CLI wanted to overwrite
`button.tsx`.** Ran `npx shadcn add alert-dialog` to scaffold the confirm
dialog; it hung on an unprompted "overwrite button.tsx?" confirmation and,
once re-run non-interactively, a `git diff` showed it had also added a
stray `cn` npm package as a dependency the project doesn't need (it
already has its own `cn()` in `lib/utils.ts`). Reverted, and switched to
`npx shadcn view <component>` (read-only) to pull the registry's real
Base UI + Tailwind source, then hand-copied each one in with imports
pointed at this project's actual conventions. Recorded as a decisions.md
entry so a future session doesn't repeat the same overwrite.

**Group B — `ChatApp`'s request lifecycle.** Replaced the separate
`pendingPrompt`/`error` `useState` pair with a `PendingState` union
(idle/submitting/loading) and a retryable `ErrorState` (`{ message,
retry }`), covering both request shapes the component makes (sending a
prompt, loading a conversation) with one "Try again" button wired to
whichever action actually failed. Added a cosmetic staged-progress
indicator (`PendingIndicator.tsx`) and a skeleton loading state for
switching conversations — both flagged explicitly as covering a gap that
already existed (a blank pane while `getConversation()` resolved), not
introduced by the refactor.

**Group C — mobile sidebar drawer.** Re-read `ChatApp.tsx` first and
found the sidebar was already collapsible on both breakpoints (Trip Hub
v2 had shipped that mid-session) — so the actual remaining gap was mobile
specifically pushing the compose box off-screen with a full-width inline
block, not "no collapse at all." Added a `useIsMobile` hook and rendered
the sidebar as an overlay `Sheet` on mobile only, inline column unchanged
on desktop.

**Real bug avoided before it shipped: a CSS-only mobile hide would have
been a focus-trap.** First instinct was `md:hidden` on the `Sheet` so it
could stay mounted unconditionally; caught before writing it that a
mounted-but-CSS-hidden Base UI `Dialog` stays "open" as far as focus
trapping and scroll locking are concerned, which would silently break
desktop keyboard navigation whenever `sidebarOpen` was true. Used a real
`useSyncExternalStore`-based breakpoint check to decide which component
*mounts* instead.

**Group D — route-level error/loading states for the Trip Hub pages.**
Re-read again and found Group D's original ask (pull the itinerary out of
chat scroll into a persistent view) was already built more thoroughly
than planned — `/trips`, `/trips/[tripId]`, `TripHubPanel` all existed.
The real remaining gap: `listTrips()`/`getTrip()` failed open to `[]`/
`null` on *any* failure, so a backend outage rendered identically to "you
have no trips" on `/trips` or a hard 404 on `/trips/[tripId]` — silently
misleading, same class of bug Group B had just fixed inside `ChatApp`,
just not extended to these two newer routes. Gave both a typed `{ ok,
notFound?, error? }` result, added a shared `RouteErrorState` component,
`loading.tsx` for both routes, a themed `error.tsx` boundary, and a
themed `not-found.tsx` replacing Next's unstyled default.

**Verification, throughout.** `tsc --noEmit`, `eslint`, and (once, at the
end) a full `next build` all clean after every group. Spot-checked live
in the dev server browser preview where possible (login page, skip link
keyboard-focus reveal, the new themed 404, console/server logs) — the
authenticated chat flow itself still isn't reachable by the agent (real
Google OAuth), so those code paths were verified by types + lint +
reasoning about the Base UI API surface rather than a live click-through,
called out explicitly rather than implied.

Shipped as two commits, one PR each (both merged via a merge commit,
branches deleted after): #24 for the code (branch `frontend-ui-ux-pass`),
#25 for STATUS.md/decisions.md (branch `docs-frontend-ui-ux-pass`).

## 2026-09-04 — Trip Hub chat column now fills available width

Follow-on to the accordion fix, same day: the user pointed at the
`/trips/[tripId]` Trip Hub page and asked for the chat block (header,
message list, composer) to be "horizontally dynamic." `ChatApp.tsx`'s
`<main>` carried a flat `mx-auto max-w-3xl` cap regardless of context —
the right call on the plain `/` chat, where `<main>` is the whole row,
but on the Trip Hub page (with `TripHubPanel` as a shrink-0 sibling) it
left the 768px-capped chat column centered in whatever space was left
over next to the panel, instead of filling it — large uneven gaps on any
reasonably wide viewport.

Fix: the cap now applies only when `ChatApp` is rendered without a
`rightPanel`; with one, `<main>` drops to a plain `w-full` and stretches
to whatever width the flex row actually gives it. Message bubbles
(already `max-w-[80%]` of their container) and the itinerary cards inside
them get the same benefit for free. Verified with a static before/after
HTML reproduction of the same flex layout (real login still isn't
possible for the agent) — confirmed the dead gap is gone and the chat
column now fills the row next to the panel.

## 2026-09-04 — Accordion collapse was never actually animating

Follow-on, same day, after "lock the chat header/composer" shipped: the
user asked that collapsing a Day card in the trip view let the following
cards reflow up into the freed space, from a screenshot of the real
running app. `frontend/src/components/ui/accordion.tsx` already applies
`data-open:animate-accordion-down`/`data-closed:animate-accordion-up`,
but no `accordion-down`/`accordion-up` keyframes existed anywhere in the
project — no `tailwind.config.*` file at all (Tailwind v4, CSS-native
config), and `globals.css`/the `tw-animate-css` package both lack them.

That mattered functionally, not just cosmetically: base-ui's
`useCollapsiblePanel` (shared by Accordion and Collapsible) decides how a
panel closes by reading the *computed* `animation-name`/`-duration` off
the panel element. With no real keyframe animation detected, it falls
back to `animationType: 'none'` and unmounts the panel synchronously on
close — which sounds like it should still reclaim space instantly, and
does, but reads to a user as the card's content "just disappearing"
rather than the layout dynamically reflowing, which is what was reported.

Fix: added real `accordion-down`/`accordion-up` `@keyframes` (interpolating
`height` against the `--accordion-panel-height` var the panel already
exposes) plus matching `--animate-accordion-down`/`-up` entries in
`globals.css`'s `@theme inline` block, so the classes already referenced
in `accordion.tsx` resolve to a real CSS animation instead of a no-op.
Verified with a minimal static HTML reproduction of the same CSS
contract (served locally, viewed via the browser tool) rather than
through the real app, since logging in as the automated agent still
isn't possible — confirmed a collapsed card now animates shut and the
next card visibly moves up to fill the space.

## 2026-09-04 — Chat header and composer locked in place

Small layout request in between the Ticketmaster work and the accordion
fix: the user wanted the chat title/header pinned to the top and the
composer pinned to the bottom of the `/` chat page, with only the
message list itself scrolling — the whole page had been scrolling as one
block. Fixed in `ChatApp.tsx` by switching the outer container from
`min-h-screen` to `h-dvh overflow-hidden` (a fixed-height shell instead
of one that grows with content) and splitting the page into three
explicit regions: a `shrink-0` header, a `min-h-0 flex-1 overflow-y-auto`
scrollable middle, and a `shrink-0` footer. The `min-h-0` on the middle
region turned out to be load-bearing, not decorative — a flex child's
default `min-height: auto` silently blocks it from ever shrinking or
scrolling in a column flex layout without it. Verified with a static
HTML reproduction of the same three-region CSS contract, since logging
into the real app as the agent still isn't possible.

## 2026-09-04 — Ticketmaster event discovery, with a real live-caught matching bug

A third planning round the same day, started from the user describing a
new feature idea in passing ("I am also planning to add ticket master
api...") rather than a concrete request — verified the API was actually
workable within the $0 budget (5,000 requests/day, free, no card,
confirmed live) before treating it as real scope, the same discipline
already applied to Places/Pexels. Three scope questions
(`AskUserQuestion`) settled the shape before planning: interests read
fresh from the prompt each turn (explicitly NOT pulling the
cross-trip-memory roadmap item forward); discovery on-demand only; an
event can set `start_date`, with a 1-2-day settle-in buffer.

The user then supplied a real Ticketmaster Consumer Key + Secret directly
in chat — verified live immediately (a real Miami Heat game came back
with full date/venue/classification data) before planning around it, and
confirmed only the Consumer Key is actually needed for Discovery API
reads (the Secret is for signed Commerce/checkout calls, out of scope,
never stored).

One more scope question, genuinely undecided rather than assumed: since
"any jazz shows nearby?" (browsing) and "build the trip around that one"
(committing) both call the same `find_events` tool, how should the
system tell them apart without silently overriding dates on a question
that was never a commitment? Settled on requiring explicit commit
phrasing in the request's own wording, detected via a structured
`COMMITTED_EVENT_ID: <id>` marker line the model is instructed to emit
only on genuine commitment — not the model's own judgment call about a
tool result, and not fuzzy prose parsing on the consuming end.

**The key architectural finding, from a second Explore-agent pass**: no
new `TripRequest` field or frontend change was needed at all. The Saved
Places work from earlier the same day had already built the exact
plumbing this needed — `_run_tool_loop`'s raw tool-call results already
flow up through `generate_itinerary`'s `result["found_places"]` for
`routers/trips.py` to consume once a `Trip` row exists. Events reused
that channel directly.

**A real bug caught by live-testing before calling this done, not
assumed correct from the API docs**: after implementation, a live check
with `keyword="jazz"` returned "Miami Heat vs. Utah Jazz" — a basketball
game, matched on the opposing team's name, not an actual jazz show.
Ticketmaster's `keyword` param turned out to be literal full-text name
matching, not genre matching. Tested `classificationName` instead
(first against Miami directly — zero results, which briefly looked like
the fix didn't work — then against New York, which correctly returned
five real, named jazz shows; Miami genuinely just had none listed at
that moment, a content gap, not a bug). Confirmed the fix also holds for
a sports interest (`classificationName=basketball` returned real Heat
games, no false positives) before shipping it.

## 2026-09-04 — Trip Hub v2, Saved Places, and Pexels photos all shipped

Planned in two rounds (`EnterPlanMode`/`ExitPlanMode`, both approved
before writing code) and implemented across a single session, continuing
directly from the previous day's design work.

**Round 1 — Trip Hub v2 into the real app.** Two Explore-agent passes
first, to find the real gap between the mockup and the code: no trips-list
endpoint existed at all (trips only ever lived embedded inside chat
messages), no `Collapsible`/`Sheet` primitive was installed, and two of
the mockup's three Trip Hub cards (Flight, Saved Places) had zero backend
data behind them. Scoped explicitly with the user to build everything
*except* those two cards, and report back what got skipped.

Shipped: Dusk City palette wired into `globals.css` (replacing the old
teal/amber, `--ring` derived one step lighter than `--primary` since the
palette research never specified a separate ring value); the real
assistant-bubble tour-guide fix (three new `--chat-assistant-*` tokens,
same attribute-selector mechanism the primary swap already used); a
hand-rolled collapsible sidebar (skipped adding a new shadcn primitive —
this project's `@base-ui/react` base made a CLI-generated `Collapsible`
enough of an unknown that plain conditional rendering was simpler and
more reliable); a new `GET /trips` endpoint with `trip_status.py`
deriving draft/upcoming/completed in real Python, never guessed by the
LLM; and new `/trips` + `/trips/[tripId]` pages, the latter reusing
`ChatApp`'s existing rendering via two new optional props rather than
building a second chat renderer.

**Round 2 — the two skipped cards, on request.** The user asked to
integrate Saved Places and Pexels photos too, "give me steps," which
became a second planning pass (another Explore agent, focused this time
on exactly where in the request lifecycle a `Trip` row exists relative to
the tool-calling loops, and the real client/service pattern to mirror).
Confirmed with the user up front: places auto-save, no manual save
button — building one would need structured place cards in the chat UI
first, real scope beyond persistence. Implementation touched
`agent_service._run_tool_loop` itself (now returns raw tool-call results
alongside the reply text, shared by all three tool loops, filtered to
Places-only at the consumption site in `routers/trips.py`) and added a
new `pexels_client.py`/`pexels_service.py` pair mirroring the existing
Google Places/weather client-service split (fetched once per trip, no
TTL — a photo doesn't go stale the way a forecast does).

**Two real bugs found and fixed post-integration, not during it — both
reported live by the user clicking through the actual result:**

1. *"Only 3 trips but I see 7."* `GET /trips` was listing every `Trip`
   row unfiltered, but `generate_trip` creates a new row on every edit
   turn rather than updating one in place — confirmed against the user's
   real data (one Miami conversation, refined 4 times, 4 rows). Fixed to
   show the latest `Trip` per conversation. The first fix attempt (a
   single `GROUP BY coalesce(conversation_id, id)` query, to keep
   conversation-less orphan trips ungrouped) had its own bug, caught by
   writing a test for exactly that orphan case before trusting the fix:
   `Trip.id` and `Conversation.id` are independent sequences that can
   produce the same number, so an orphan's own id collided with an
   unrelated trip's real `conversation_id` in the test and wrongly merged
   them. Replaced with two separate, unioned queries — structurally
   collision-proof, not just unlikely to collide in practice.

2. *"It did not work, I cleared the cache, I still don't see [night
   skyline photos]."* Not a caching bug — the user's real trips had
   already fetched and permanently cached their photo on an earlier
   `/trips` load, *before* the night-skyline-first query change landed a
   few messages later (a destination's photo is fetched once, ever, by
   design). Diagnosed by reading the live `trips` table directly and
   comparing `photo_fetched_at` timestamps against when the code actually
   changed, not by guessing; fixed by clearing the three affected rows'
   cached photo columns live and re-verifying the correct query fired.

Also caught mid-flight, before it ever reached the user: applying the new
Alembic migrations to the live Neon dev database, `main.py`'s
`Base.metadata.create_all()` safety net turned out to have already
silently created the `saved_places` table (on a dev-server auto-reload)
with a too-narrow `price_level` column, from before that column's width
was corrected in the model — caught by inspecting the live schema
directly after "successfully" running the migration, not by trusting its
exit code, and fixed with a follow-up migration.

**Skipped, confirmed with the user, reported explicitly after
integration**: flight tracking — still no backend data source of any
kind, a genuinely separate feature.

**Repo hygiene**: everything above committed in one branch/PR from a
clean `main` (confirmed zero open PRs and zero stale branches beforehand),
alongside this doc update.

## 2026-09-03 — "City Passport" built and rejected; "Trip Hub v2" is the direction

Continued the same day's design work past the palette choice below into a
full UI direction pass, working from four explicit requirements: no
AI-slop button/gradient styling, not robotic/sanitized, "city-looking" so
the user feels like a tourist, and no tool/data card shown before it's
actually been fetched.

**First attempt — "City Passport"**: reframed the whole interface as a
travel document instead of a dashboard — a boarding-pass photo strip,
perforated tear-lines, rotated "ink stamp" result cards, a literal
"Passport" app tab of past trips as stamped pages. Researched real dark-mode
practice (avoid near-black, layer warmth, ambient glow) after the first
pass read as cold; researched and confirmed Pexels' API as the real
free-tier photo source (200 req/hr, no cost, no card); embedded real
CC-licensed Wikimedia Commons photos (Lisbon/Kyoto/Marrakech, credited) for
the mockup itself since the artifact sandbox can't hotlink external images.
Built out to a full website-shell + two-app-screen mockup. **User rejected
the whole direction outright** ("forget about city passport i do not like
the idea") once it was fully built — the boarding-pass/stamp metaphor
itself was the problem, not the execution. Both artifacts are kept, linked
from `docs/design-references.md`, as a recorded dead end.

**Second attempt — "Trip Hub v2", the direction going forward**: the user
supplied a PDF export of the original `Itinera UX Directions` canvas's
"Trip Hub" screens (a trip list and an active-trip working view) and asked
for "2 pages similar to this" instead. Extracted its real content via
`pdftotext -layout` (no PDF-rendering tool was available in-session) and
rebuilt it faithfully as clean, standard product UI — same Dusk City
palette and photo-thumbnail treatment carried over from City Passport, but
dropped every travel-document affectation (no stamps, no tear-lines, no
rotation). Then iterated twice more on request:
- Added a working hamburger toggle to collapse/expand the trip sidebar on
  both pages — first pass collapsed it via `width: 0`, which silently broke
  at the responsive stacked breakpoint (leftover content still claimed a
  full row's height, pushing everything else off-screen); fixed by
  switching to `display: none`, verified at both breakpoints.
- Added a second, independent collapse control (a chevron sitting on the
  Trip Hub tools column's own edge, per the user's choice among four
  offered patterns) for the Weather/Flight/Saved-Places column — collapses
  to a thin labeled rail rather than disappearing outright.
- Finally set **both** the sidebar and the tools column to start collapsed
  by default on page load, opened only on request — the strongest version
  of the "nothing pre-printed" requirement, now applied to the chrome
  itself and not just the data cards.

All three toggle states were verified with direct DOM/computed-style
checks (`getComputedStyle`, `getBoundingClientRect`) rather than
screenshots after the browser tool started returning stale frames on
scroll partway through this session — a tool-side quirk confirmed not to
be a page bug, not worth chasing further once the programmatic checks
passed.

**Repo hygiene, same session**: swept for unmerged work before starting
real frontend integration. Confirmed (by content, not just PR status —
e.g. `google_places_client.py` present on `main`, `card.tsx` absent) that
every previously-open branch was already fully merged; deleted two stale
local branches (`chore/gitignore-gaps`, `docs/design-references`) whose
squash-merged content already lived on `main` under different commit SHAs.

## 2026-09-03 — Palette direction chosen (Dusk City); UX canvas recolored

Picked **Direction C, "Dusk City"** (indigo primary + copper tour-guide
accent) from the four candidates in `Itinera Palette Directions`. Exact
values now recorded in `docs/design-references.md`: primary
`oklch(0.45 0.11 265)` (light) / `oklch(0.72 0.16 266)` (dark),
tour-guide accent `oklch(0.58 0.15 55)` / `oklch(0.80 0.17 62)`, plus the
assistant-bubble tint values for the `ChatMessage.tsx` fix that's still
outstanding.

Recolored the **Itinera UX Directions** canvas to preview the choice:
found the whole canvas leaned on just 3 oklch tokens for its teal brand
color (one dominant primary token used 19 times, a darker text variant
used 8 times, one gradient companion used once) — a global find/replace
swapped all three to Direction C's indigo family, republished to the same
artifact URL. The canvas's tour-guide-mode toggle chips are still styled
neutral gray, not recolored to the copper accent — they're plain-text
JS-string-encoded content inside the canvas's rendered export, not
something safe to hand-edit precisely, so that's left as a possible
follow-up rather than risking a broken patch. Also caught and fixed a
title regression from this: the file's `<title>` tag sits past the 8KB
scan window the publish path uses to auto-detect a title, so the redeploy
briefly fell back to the filename (`ux-directions-dusk-city`) until an
explicit `title` param on the next publish corrected it back to
"Itinera UX Directions" — worth remembering for any future edit-and-
republish of this same exported-canvas file.

**Not done yet, explicitly deferred**: wiring Direction C's tokens into
the real `frontend/src/app/globals.css` (`--primary`/`--ring`/
`--sidebar-primary`/`--sidebar-ring` + the tour-guide override block),
applying the assistant-bubble tint to `ChatMessage.tsx`, and the WCAG AA
contrast check that was already flagged as needed for any non-Direction-A
palette. The live app still renders the old teal/amber palette — only the
design canvas preview and the docs reflect the new choice so far.

## 2026-09-02 — Documentation rebuild, gitignore hygiene, and three design artifacts

**Documentation rebuilt into this four-file structure**
(README/STATUS/decisions/progress), replacing the sprawling `CLAUDE.md`
decision table and the 21-file `docs/sessions/` diary — `CLAUDE.md` kept
as a slim pointer since it's the file Claude Code auto-loads as project
instructions, not deleted outright. Shipped as PR #11 (a small
design-references doc, merged) then PR #13 (the actual four-file
rebuild) — the first attempt at the rebuild PR (#12) was accidentally
auto-closed by GitHub when its base branch was deleted on #11's merge,
and couldn't be reopened; re-created against `main` directly instead,
no content lost.

**Three `.gitignore` gaps found and fixed** (PR #14): `graphify-out/*`
had a slash in the middle, which git anchors to the directory the
`.gitignore` lives in — so it only matched a top-level `graphify-out/`
and silently missed a nested `frontend/graphify-out/` that was sitting
untracked on disk (same bug *shape*, inverted, as the documented `lib/`
shadowing incident: that one was too broad, this one too narrow); no
root-level OS-junk coverage (`.DS_Store` was frontend-only, `Thumbs.db`/
`desktop.ini` uncovered anywhere); and no rule yet for Claude Code's own
per-user `.claude/settings.local.json`. All three fixed. Also removed
`Learnings.txt` (deleted from disk by the user outside this session,
committed on explicit confirmation it should stay gone).

**Three design artifacts published**, all still pending a decision as
of this entry:
- An **architecture diagram**, correcting a hand-drawn sketch that had
  collapsed the classifier's four branches and the LLM/direct-call
  distinction into fewer boxes than the real system has.
- A **UX directions canvas** (web + app mockups) built around a "Trip
  Hub" concept — the itinerary becomes a persistent structured record
  instead of living only inside chat scroll — with a mocked-up
  flight-tracking screen for the feature scoped the same session.
- A **palette research page**: four travel-evocative color directions
  (Ocean & Golden Hour — the current teal/amber, refined; Terracotta &
  Sage; Dusk City; Trail & Canyon), each with a live chat-bubble mockup
  in both themes. Found a real, previously-undocumented gap while
  building it: `ChatMessage.tsx`'s assistant bubble is always plain
  `bg-card` — tour-guide mode today only ever recolors the *user's own*
  bubble. Every mockup on the page fixes this with a soft accent-tinted
  assistant bubble; not yet applied to the actual component.

See `docs/design-references.md` for all three links. **Next**: neither
Maps/routing nor flight price-tracking has started; no palette direction
has been picked yet either — see STATUS.md.

## 2026-09-01 — Conversation-context truncation bug

`_build_conversation_context` joined the last 6 messages chronologically
then applied a plain `[:MAX_CONTEXT_CHARS]` slice — keeping the oldest
content and dropping the newest once over budget. Real symptom: a user
discussed scuba diving, said "can we add to the plan," and got an
itinerary with zero mention of diving because the truncation had cut the
scuba content out of the context before generation ever saw it. Fixed by
building from the most recent message backward, only dropping the oldest
when the budget is tight. Shared by `classify_intent` too, so this
benefits intent classification on long conversations, not just edits.

## 2026-09-01 — Intent misclassification: recommendations & tour-guide triggers

Two bugs from one real conversation: (1) "I think i am already at wynwood
walls i really want understand the importaance of the place" didn't
trigger tour-guide mode — the trigger list only recognized literal
phrasing ("be my tour guide"), not the same request worded differently.
(2) "can you suggest a place where i can go but still see the murals" —
a single-place recommendation ask — was misclassified as `new_trip` and
regenerated an entire unrelated 5-day itinerary. Fixed with concrete
`INTENT_INSTRUCTIONS` examples for both, live-verified against the exact
transcript with no over-correction on genuine new-trip/edit-trip/tour-guide
requests.

## 2026-09-01 — Google Places API integration

Added `get_place_details` and `find_nearby_places` (billed) alongside the
existing free Wikipedia tool, in both the QA and itinerary-planning loops.
`GOOGLE_PLACES_API_KEY`'s presence is the kill switch, mirroring
`GROQ_API_KEY`'s convention. Found and fixed a real bug live: a
landmark-level `near` value ("Louvre Museum, Paris") reliably failed
Open-Meteo's city-oriented geocoder, and the model's own retries with
broader phrasings exhausted `MAX_TOOL_ROUNDS` before the phrasing that
worked ever got summarized into an answer. Fixed with a fallback to
Google Places' own `text_search` for geocoding, resolved deterministically
in one call instead of leaving it to repeated LLM guesses.

## 2026-08-31 — Tier 2: agent_service cleanup

Silent tool-loop failures now `logger.exception`/`logger.warning` (tagged
with which of the three loops failed). Removed `agent_service.py`'s
reach into `llm_service.py`'s private internals — this codebase's one
circular import — via a new shared `gemini_client.py` owning client
construction. Fully backward-compatible with the existing test suite via
aliases; verified live the circular import is actually gone.

## 2026-08-31 — CORS, rate limiting, Tier 1 hardening

Full architecture review after an explicit user correction: this is a
real product's base, not a hobby project. `allow_origins=["*"]` replaced
with an env-driven allow-list; slowapi rate limiting added (100/min
app-wide, 10/min on `/trips/generate`). Tier 1: FK indexes on every
foreign key (Postgres never auto-indexes these), an N+1 fix on
`get_conversation`, pagination on `list_conversations`, and a real
DB-backed per-account daily quota (`DAILY_TRIP_GENERATION_LIMIT`, default
20/day) — checked before any LLM work runs. Two Alembic migrations
applied live to Neon; caught a nullable-column-with-no-server-default bug
before applying, same class already documented from an earlier incident.

## 2026-08-30 — Ultrareview findings

First `/ultrareview` pass on the branch: 5 real findings, 3 fixed in code
(a real `agent_context` caching bug, a docker-compose env gap), 2 resolved
by staging files this session had left untracked. No false positives.

## 2026-08-29 — Neon Postgres migration

Executed the already-decided MySQL → Postgres migration, prompted by the
same-day reconciliation mess (below). Caught a real bug live: a
schema-creation script silently created zero tables (forgot to import
`app.models` before `create_all()`) while still printing success — same
bug class as the `alembic/env.py` incident from OAuth Phase D. All data
migrated and verified row-for-row via `backend/scripts/migrate_to_neon.py`.

## 2026-08-29 — MySQL reconciliation

Local dev MySQL turned out to be a mix of an unrelated native Windows
service (wrong credentials, a red herring) and two genuinely divergent
real datasets: Docker MySQL vs. an accidentally git-committed SQLite
file. Kept Docker MySQL's data per user choice, upgraded it to the
current migration head, pointed `.env` at its actual port (3307),
untracked and gitignored the SQLite file.

## 2026-08-29 — Tour-guide mode refinements

Deterministic one-time activation acknowledgment (code-generated, not
LLM-phrased), brief-by-default replies (reversing an earlier
forced-detailed design once the fabrication risk that motivated it was
fixed a more targeted way), and a real UI accent-color swap (amber) while
active. Found and worked around two unrelated environment issues: an
orphaned `uvicorn --reload` worker serving stale code, and the dev MySQL
instance rejecting its own configured credentials. A same-day follow-up
fixed a real bug: a bare "be my tour guide" with no place named triggered
a full day-by-day itinerary recap instead of a short welcome — root cause
was the trigger-phrase list itself implying "dump everything," fixed by
separating persona-trigger phrasing from detail-level phrasing.

## 2026-08-29 — Tailwind/shadcn UI redesign

Frontend restyled with Tailwind CSS v4 + shadcn/ui, replacing ~350 lines
of hand-written CSS; new teal palette replaces the leftover Streamlit red.
Pure styling pass, no behavior change — but found and fixed two real
pre-existing bugs along the way: a mobile layout bug (sidebar pushed the
whole chat panel off-screen below `md` width) and an unused-font bug
(`--font-sans` was never actually wired to the loaded Geist font).

## 2026-08-29 — Wikipedia context for itinerary planning

Place-context now also grounds itinerary generation itself (a third,
isolated tool-calling loop), and the tour-guide detail cap tripled
(2000 → 6000 chars). Live-verified reliable in isolation; intermittently
silent when run as the 3rd concurrent Gemini call under this account's
free-tier rate limits — a pre-existing failure shape, not a new bug,
accepted as-is per the existing fail-quiet design.

## 2026-08-27 — Persistent tour-guide mode

New `Conversation.tour_guide_mode` — once triggered, later Q&A follow-ups
stay in the fuller narrative-guide style until the user explicitly
returns to itinerary planning. `classify_intent` extended with a
`tour_guide_requested` field on the same Gemini call, no extra cost.
Mechanical but wide-blast-radius fallout: `classify_intent`'s return type
changed from `str` to `tuple[str, bool]`, requiring 28 test mock call
sites across 4 files to update.

## 2026-08-27 — Day-count drift and tour-guide misrouting

Two live bugs: (1) itinerary day count silently drifting on a vague edit
turn with no day-count language, because `total_days` was re-guessed from
scratch every call with nothing anchoring it to what was already
established — fixed by folding the previous trip's day count into the
meta prompt as a soft, overridable fact. (2) "be my tour guide"/"take me
through this place" was misclassified as `edit_trip`, regenerating a
whole new itinerary instead of reaching the Q&A tool path — fixed by
adding concrete disambiguating examples to `INTENT_INSTRUCTIONS`. A
same-day follow-up investigated a suspected third bug (fabricated venue
names) and found one real gap: the anti-fabrication instruction only
covered a tool call returning an error, not a *successful* call getting
padded with invented extras.

## 2026-08-27 — Wikipedia place-context tool

New `get_place_context` LLM tool for conversational Q&A, via a new
tool-calling loop kept fully separate from the paused currency one.
Scoped down from a fully-researched-but-deferred Google Maps integration
(no genuinely cardless free path existed for Places API/Routes
API/Geocoding API). Live-verified brief-vs-detailed and fresh-per-turn
behavior; found and fixed a real prompt-tuning bug (the model padding
"brief" replies with its own pretrained knowledge).

## 2026-08-26 — Codebase cleanup pass

Full dead-code/build-hygiene read-through after the OAuth work. **Most
significant finding, a real bug**: `frontend/src/lib/` (6 files —
Server Actions, JWT bridge, shared types) had never been committed to
git since the initial commit, silently swallowed by a too-broad
`.gitignore` pattern (`lib/`, meant for a Python build directory,
matching at any depth). Fixed by anchoring the pattern to the repo root.
Also removed one dead export, added a missing `backend/.dockerignore`
(261MB → 772B build context), split test-only deps into
`requirements-dev.txt`.

## 2026-08-26 — Google OAuth Phase D (Calendar push)

Go/no-go check on the Calendar MCP server came back negative
(`google-genai`'s MCP support still "experimental," the MCP server itself
gated behind a non-GA preview program) — used `googleapiclient` directly
instead, which is also the better architectural fit independently (a
deterministic user click, not a Gemini judgment call). New
`google_calendar.py`: encrypted token storage, automatic refresh. **A
real, unrelated bug found and fixed while building this**: an earlier
`ruff --fix` had silently deleted `alembic/env.py`'s
`from app import models` import (needed only for its side effect), which
would have made the next `--autogenerate` migration **drop every existing
table** — caught by reading the generated migration before applying it,
not by trusting `--autogenerate` blindly. Same-day follow-up merged the
two-button export UI into one "Export Plan" button, and fixed a real bug
found on first live click-through: Google's Calendar API (unlike the
`.ics` file) rejects a timed event with no timezone — fixed by resolving
a real IANA timezone via Open-Meteo's geocoding response.

## 2026-08-26 — Google OAuth Phase C (ownership isolation)

Retrofit real ownership checks on every endpoint that had none —
`get_trip`, `export_trip_calendar`, `get_conversation`,
`delete_conversation` all gained `Depends(get_current_user)` plus a
`user_id == user.id` filter (404, not 403, on a cross-user id).
`TripRequest.user_id` (client-trusted, exactly as untrustworthy as the
old `DEFAULT_USER_ID` query param) removed from `schemas.py` entirely,
not just unused. 6 new cross-user isolation tests.

## 2026-08-26 — Google OAuth Phase B (login)

Auth.js Google login + JWT bridge to FastAPI, `User.google_sub`, Alembic
introduced into the project for the first time. Verified live up to
Google's real consent screen (correctly rejected placeholder credentials).

## 2026-08-26 — Next.js migration Phase A

Streamlit → Next.js migration, full UI parity (chat, sidebar, itinerary
rendering, both export buttons, the same start_date-gating rule), against
the unmodified backend, no auth yet — validating the rewrite independently
of auth risk before building login on top of it.

## 2026-08-26 — Q&A date bug and currency pause

Third distinct root cause behind the same visible symptom ("I don't have
weather data") across three separate rounds this build-order item: a
trip generated with no date phrase at all correctly had `start_date =
None`, but a follow-up question that itself named a date never got
`date_resolver` run on it — the question branch had never had
date-resolution logic in it at all. Fixed by trying date resolution on
the question's own text when the trip's `start_date` is still unset, and
persisting the result. Currency conversion paused the same day — a
product decision that it isn't needed, not a reliability finding (it was
verified working correctly two days earlier).

## 2026-08-26 — .ics calendar export

Build-order item 3. New `calendar_export.py`, pure formatting, no
LLM/network call — one `VEVENT` per itinerary item, real date arithmetic
(`trip.start_date + (day_number - 1)`), deliberately floating local time
(no `TZID`, valid RFC 5545). Export control hidden entirely (not
disabled) until a trip has a resolved `start_date`.

## 2026-08-25 — Weather feature and LLM reliability

Real per-day weather via Open-Meteo, re-enabled the currency agent step,
adopted MCP as an evaluation framework for future tools, escaped
Gemini's 20-req/day free-tier wall with a model swap (`gemini-3.6-flash`
→ `gemini-3.5-flash-lite`) plus a Groq fallback. Two live bugs found and
fixed post-ship: Q&A fabricating temperatures when nothing was cached
yet, and a missed "N days from now" date phrasing. Google's Gemma 4
evaluated and rejected as a Gemini replacement — real structured-output
and instruction-following bugs found live, not assumed.
