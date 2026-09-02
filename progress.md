# Progress — Itinera

Dated diary: what happened, what changed, what should happen next.
Consolidated 2026-09-02 from what had been ~21 individual files under
`docs/sessions/`. Newest first. For the decisions this history produced,
see [`decisions.md`](decisions.md); for where things stand right now, see
[`STATUS.md`](STATUS.md).

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
