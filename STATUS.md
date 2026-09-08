# STATUS — Itinera

Current snapshot. For why things are the way they are, see
[`decisions.md`](decisions.md). For the session-by-session history behind
this snapshot, see [`progress.md`](progress.md).

_Last rebuilt: 2026-09-02, consolidating everything documented up to that
date into this four-file structure (README/STATUS/decisions/progress).
Last updated: 2026-09-04, after Trip Hub v2, Saved Places, Pexels trip
photos, and Ticketmaster event discovery were all wired into the real
app, plus three same-day chat/Trip-Hub layout fixes: the chat header and
composer locked in place with only the message list scrolling, the Day
accordion cards actually animating shut (missing keyframes) instead of
snapping, and the Trip Hub chat column filling available width instead
of leaving dead space next to the side panel (see `progress.md`'s
2026-09-04 entries). Updated again same day after a frontend UI/UX pass
(PR #24): sidebar delete confirmation, a retryable error/loading state
in `ChatApp` and across the two Trip Hub routes, an overlay drawer for
the sidebar on mobile, and a first accessibility pass (skip link,
`aria-live` transcript, focus management). Updated once more same day
(PR #27) after a real WCAG AA contrast check on the Dusk City palette
(caught and fixed two failures in light-mode tour-guide mode) and a
follow-up accessibility pass (announced status messages, a screen-reader
speaker cue in chat, `aria-current` on the active conversation, a
labeled composer) — see `decisions.md`'s UI styling entries and
`progress.md`'s 2026-09-04 entries. Updated again 2026-09-05 (PR #29)
after fixing a real "chat switching looks like a full page reload" bug:
`ChatApp.tsx` was split into a persistent `ChatShell.tsx` (sidebar,
message log, composer) living in a new shared `app/(chat)/layout.tsx`
route group, plus a small `OpenConversation.tsx` bridge each page uses to
tell it which conversation to open — see `decisions.md`'s UI styling
entries and `progress.md`'s 2026-09-05 entry for the full diagnosis
(a real remount-and-repeated-fetch bug, confirmed via two DevTools
Network-tab captures, not a React Strict Mode artifact). Updated again
2026-09-05/06 (PR #31, #32) after a full-codebase maintainability audit
(a short, low-risk list — dead code, duplicated logic, a couple of real
config gaps — see `progress.md`'s 2026-09-05/06 entry) and adding
`docker-compose.share.yml` for running the app from CI's published
images with nothing but Docker installed. Updated again 2026-09-06
(PR #33) after splitting the two things that audit deliberately deferred:
`generate_trip` into three named helper functions, and `ChatShell.tsx`
into three hooks (`use-sidebar-open`, `use-scroll-restore`,
`use-conversation-loader`) — both pure structural refactors, verified
both by CI and by the user manually against a real signed-in session
(see `decisions.md`'s Architecture and UI styling entries). Updated once
more 2026-09-06 after a four-part security pass: a frontend secrets audit
and a full git-history secret scan both came back clean (PR #35 closed
one real gap found while checking — root `.gitignore` didn't cover
`.env.local`/`.env.production` variants); a Supabase-style anon-vs-
service-role key check came back not-applicable (no Supabase, no
client-side DB access exists at all); row-level security was
investigated and found to need real session-identity plumbing this app
doesn't have yet, so it was **not** enabled (see `decisions.md`'s new
Database access control entry) — authorization stays enforced at the API
layer only. Also fixed a real bug (PR #36): `/login` had no check for an
already-authenticated user and would show the sign-in form instead of
redirecting; verified live against the user's real signed-in session.
Updated again 2026-09-06 after building onboarding personalization end to
end: a `UserProfile` table (two additive migrations), `GET/PUT /profile`
+ `POST /profile/onboarding/skip`, real prompt-injection wiring into
`generate_itinerary`, and a 4-step `OnboardingFlow` dialog (Account
details → Trip style → Habits & logistics → Goals) gated in
`app/(chat)/layout.tsx`. A mid-build correction: account-details fields
(mobile, DOB, country) were first scoped out entirely for having no real
consumer, then rebuilt once genuine features were committed to (DOB now
drives real age-bracket personalization; SMS reminders remain deferred,
sending needs an external provider). Followed by a "leave nothing
behind" pass: real phone/DOB validation (client + authoritative
server-side), a hand-built toast system (Itinera's first ambient-
notification primitive), a real `/profile` page reusing `OnboardingFlow`
in edit mode (closing a dead end — the page was referenced in a
docstring but unreachable), and this frontend's first-ever automated test
suite (Vitest + React Testing Library, 12 tests). Caught and fixed one
real bug along the way: every onboarding `<select>` was unreadable in
dark mode (native popup rendering light-on-white) — one shared CSS fix,
verified compiled into the production bundle, plus a regression test.
See `decisions.md`'s new Onboarding personalization entry for the full
detail, including what's still genuinely open (SMS sending, and a real
signed-in click-through — verification stopped at the OAuth handshake
itself, which needs the user's own Google credentials)._

_Updated 2026-09-07 after building and merging four follow-on gaps
flagged by the onboarding pass above, as four isolated branches — **PRs
#39–42, all merged to `main`**: (1) onboarding's plain `<select>`/
checkbox fields replaced with a real interactive chip control (PR #39);
(2) an Events Trip Hub card, live per-trip Ticketmaster fetch cached on
the `Trip` row with a 6h TTL, mirroring weather's existing pattern
exactly (PR #40); (3) the auth-testing gap closed with
`docs/manual-auth-testing.md`, a human-run runbook, plus a real unit
test on the JWT signer — not new pytest/E2E infrastructure, since the
backend half was already fully mocked (PR #41); (4) gamification
(passport stamps + tiered badges) built for the first time, on the
existing `/profile` page (PR #42) — see `decisions.md`'s new "Four
follow-on features" entry for the full detail on all four, including two
real bugs caught during implementation: a `Trip.is_edit` correctness fix
(every `edit_trip` turn was silently going to inflate trip counts/badges
the same way a new trip would) and a real dark-mode theming bug
(Tailwind `dark:` classes silently never apply in this app at all — this
app's dark mode is media-query-driven, not `.dark`-class-driven — fixed
with real CSS custom properties for the new stamp accents). PR #42's
migration chained after PR #40's, so #40 was merged first; each PR's
branch was updated with `main` and its own CI reverified green before
merging (one real merge conflict in `models.py`, resolved by keeping
both branches' new `Trip` columns).

Separately, while opening these PRs, found and fixed **`main`'s CI
itself was broken**, in PR #43 (merged first, before the four above) —
every PR was failing CI in under 20 seconds on two pre-existing issues
from PR #38's merge, unrelated to any of the four features: an
`npm ci` `ERESOLVE` conflict (`@types/node` pinned too old for
`vitest@5`) and an unsorted-import `ruff` failure._

_Updated again 2026-09-07 (PR #45) after redesigning and rebuilding
`/login` end to end. Requested as a traditional email/password
login-vs-signup page; corrected before building anything, since this
app has only Google OAuth (no password system, no separate signup
flow — one button already handles both, see `decisions.md`'s Auth
entry). Landed in three passes on the same PR: (1) a small
copy-only fix (a reassuring line clarifying Google sign-in also
creates the account); (2) a full visual redesign approved first as a
mockup artifact, then integrated for real — a new `LoginCard.tsx`
with a Login/Signup chip-tab toggle (reusing `toggle-chip.tsx` from
onboarding), Google (real), and Facebook/email-password drawn to
visual parity but honestly toasting "not available yet" rather than
faking a login, since neither has a backend; (3) a "Dusk City"
background (gradient + inline SVG skyline, this app's own two named
hues, no photo asset) added per follow-up feedback, then deliberately
kept over a later request to swap it for live Pexels photos — declined
to avoid a new public unauthenticated backend endpoint and a
third-party dependency on the app's most reliability-critical page.
Two real bugs caught during integration: this app's global
`overflow: hidden` on `html`/`body` would have trapped the login
card's own overflow content on a short viewport (fixed by giving the
page its own `h-screen`/`overflow-y-auto` scroll region); and the
email "submit" button relied on native `<form onSubmit>`, which this
app's `Button` primitive doesn't reliably forward — fixed by switching
to the `onClick`-only convention `OnboardingFlow.tsx` already
established. See `decisions.md`'s new Login page redesign entry for
the full detail._

## Where the project stands

**Product**: a chat-driven AI trip planner. Describe a trip, get a
day-by-day itinerary, refine it conversationally, export it to Google
Calendar. Full scope (weather, place context, calendar push, per-user
accounts) — done. **Onboarding personalization is live**, and its
chip/tag visual polish, an Events Trip Hub card, and gamification
(passport stamps, tiered badges) are all now **live too** (PRs
#39/#40/#42, merged — see this file's 2026-09-07 update above).
Maps/routing, flights, hotels, cross-trip memory — not started.

**Backend**: FastAPI + SQLAlchemy, Postgres on Neon. Every request goes
through one router (`POST /trips/generate`) — see `decisions.md`'s
Architecture entry for the flow, or the published
[request-flow diagram](design-references.md) for a visual trace.

**Frontend**: Next.js (App Router, TS), Tailwind v4 + shadcn/ui, now
running the **Dusk City palette live** (indigo primary, copper tour-guide
accent) in `globals.css` — both chat bubbles tint on tour-guide mode now,
not just the user's own (a real gap found during the earlier palette
review, fixed as part of this integration). **Trip Hub v2 is live**: a
collapsible conversation sidebar (closed by default) on the main chat, a
new `/trips` page (real trip cards — status pill, day count, a real
per-city photo), and a new `/trips/[tripId]` Trip Hub page (the existing
chat UI reused via the persistent `ChatShell` component — see this file's
2026-09-05 update below — plus a collapsible data column with Weather and
Saved Places cards) — the chat column there now fills whatever width the
row gives it next to that panel, instead of sitting in a fixed-width
column with dead space beside it. The earlier "City Passport" (travel-document/boarding-pass)
direction stays a rejected dead end, not touched. A same-day UI/UX pass
added: a real confirm dialog before deleting a chat; a retryable
error/loading state in `ChatApp` (`PendingState`/`ErrorState` unions,
replacing ad hoc booleans) and — separately — in `listTrips()`/`getTrip()`,
which used to fail open to `[]`/`null` and render "no trips"/404 on a
plain network blip; an overlay `Sheet` drawer for the sidebar on mobile
instead of a full-width block that pushed the composer off-screen; and a
first accessibility pass (skip link, `aria-live` on the message
transcript, focus returning to the composer after a send, `#main-content`
landmarks). A same-day follow-up (PR #27) ran a real oklch->sRGB contrast
check on the Dusk City palette — found and fixed two AA failures, both
in light-mode tour-guide mode (the copper accent was darkened from
`oklch(0.58 0.15 55)` to `oklch(0.45 0.15 55)`) — plus a second
accessibility pass (announced status messages, a screen-reader speaker
cue in chat, `aria-current` on the active conversation, a labeled
composer). **Onboarding personalization is live**: a 4-step
`OnboardingFlow` dialog (Account details → Trip style → Habits &
logistics → Goals) gates on first login (`app/(chat)/layout.tsx`), saves
through `PUT /profile`, and is reused unchanged in edit mode from the new
`/profile` page (linked from the sidebar) — one component, two entry
points, per the original design intent. Real phone/DOB validation, a
hand-built toast system (`components/ui/toast.tsx`, this app's first
ambient-notification primitive) confirming a successful save, and this
frontend's first-ever automated test suite (Vitest + React Testing
Library) all shipped in the same pass — see `decisions.md`'s Onboarding
personalization entry for the full detail. The chip/tag visual polish
pass on onboarding fields is now live (PR #39) — a real interactive chip
control (`components/ui/toggle-chip.tsx`), not just a styling change.
The `/profile` page also now has a passport-stamps-and-badges section
(PR #42, gamification). No native/PWA app exists yet.

**LLM**: Gemini API (`gemini-3.5-flash-lite`), Groq as an automatic
fallback on rate-limit only. Not wired into the agentic tool-calling
loops, only into `llm_service.py`'s direct calls (classifier, generation,
plain Q&A).

## Live vs. paused right now

| Capability | State |
|---|---|
| Itinerary generation (chunked, Gemini structured output) | Live |
| Intent classification (4-way: new_trip/edit_trip/question/off_topic) | Live |
| Real per-day weather (Open-Meteo, direct call, never an LLM tool) | Live |
| Wikipedia place context (`get_place_context`) | Live, free |
| Google Places tools (`get_place_details`, `find_nearby_places`) | Live, billed — key set |
| Saved Places (auto-persisted `find_nearby_places`/`get_place_details` results) | Live — shown on the Trip Hub page, only once a place has actually been found |
| Event discovery (`find_events`, Ticketmaster) | Live, free tier — key set. On-demand only; a committed-to event can set a trip's `start_date` (2 days before, for settle-in time), but only on explicit commit phrasing |
| Persistent tour-guide mode | Live, both chat bubbles now recolor |
| Trip photos (Pexels, "{destination} skyline at night" first, plain name as fallback) | Live, billed-free tier — key set |
| Your Trips / Trip Hub pages (`/trips`, `/trips/[tripId]`) | Live |
| Google OAuth login + per-user data isolation | Live (needs a real `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` to actually sign in) |
| Redesigned `/login` page (Login/Signup toggle, Dusk City background) | Live ([PR #45](https://github.com/starkparsa/Itinera/pull/45)) |
| Email/password authentication (`/auth/register`, `/auth/login`, bcrypt) | Live ([PR #47](https://github.com/starkparsa/Itinera/pull/47)) — same session/onboarding flow as Google, via Auth.js's Credentials provider and a `provider` JWT claim |
| Google Calendar push ("Export Plan") | Live |
| Currency conversion (`gather_trip_context`/`convert_currency`) | **Paused** — product decision, not a bug. Kill switch: `AGENT_TOOL_CALLING_ENABLED` |
| Groq fallback | Live, verified |
| Onboarding personalization (`UserProfile`, `OnboardingFlow`, `/profile`) | Live — feeds `generate_itinerary`'s prompt; visual chip/tag polish also live ([PR #39](https://github.com/starkparsa/Itinera/pull/39)) |
| Toast notifications (`components/ui/toast.tsx`) | Live — consumers: onboarding's save confirmation and gamification's badge-unlock notice |
| Events Trip Hub card | Live ([PR #40](https://github.com/starkparsa/Itinera/pull/40)) — per-trip fetch, 6h TTL, no new table |
| SMS trip-day reminders | Not built — `mobile_number` is collected, sending needs an external provider evaluated against a real free tier first |
| Gamification (passport stamps, tiered badges) | Live ([PR #42](https://github.com/starkparsa/Itinera/pull/42)) |
| Flights (tracking/predicting/booking) | Not built — no backend data source exists at all; deep-link booking scoped, price tracking blocked on a verified free data source |
| Hotels | Not built |
| Maps/routing | Not built — planned around Google's Maps MCP server |
| Cross-trip preference memory (pgvector) | Not built — deliberately last |
| PDF export | Deferred indefinitely |

## Next action

PRs #43, #39, #40, #41, #42 are all merged to `main` as of 2026-09-07 —
none of the three build-order candidates below depend on any of that
work. Gamification was an intentional, discussed jump ahead of
Maps/routing in this order, not a silent reorder (see `decisions.md`'s
"Four follow-on features" entry). One item still open from the
onboarding pass, not resolved by any of the four: a real signed-in
click-through of `OnboardingFlow` — a documented runbook now exists
(`docs/manual-auth-testing.md`, PR #41) but actually running it needs
the user's own Google credentials, still not automatable. Doesn't block
the three below:
1. Build-order item 4: Maps/routing (planned around Google's Maps MCP
   server — the specific server/pricing/auth details need re-confirming
   live before writing code, per `decisions.md`'s Maps/routing entry).
2. Resolve the flight price-tracking data-source question
   (Travelpayouts/Aviasales — unverified). Flight tracking is the one
   Trip Hub card still with zero backend data behind it.
3. ~~No frontend surface for events exists yet~~ — resolved by PR #40.

## Known blockers / open items

- **SMS trip-day reminders need an external provider evaluated against a
  real free tier** — `mobile_number` is collected (a real, committed
  feature), but sending itself, a scheduling mechanism, and opt-in UX are
  all separate, larger scope not yet started.
- **A real signed-in click-through of onboarding hasn't happened** —
  everything up to the OAuth handshake was verified live against real
  running servers; completing sign-in needs the user's own Google
  credentials, which isn't something to automate. `docs/manual-auth-testing.md`
  (PR #41) is now the documented runbook for actually doing this — the
  blocker is running it, not knowing how.
- **Flight tracking has no backend data source at all** — the one Trip
  Hub card still genuinely unbuilt, not merely unwired.
- **Google OAuth consent screen is still in "Testing" status** — caps
  refresh tokens at 7 days. Publishing to Production needs a human in
  Google Cloud Console; explicitly deferred until there's a real domain
  to publish against (see `decisions.md`'s Deployment entry).
- **No native/PWA app exists** — a real engineering decision (React
  Native vs. PWA vs. native) not yet made.
- **No user research behind the current UX direction** — built from
  feature docs and engineering history, not measured usage.
- **Database has no row-level security** — a single Postgres role serves
  the whole backend with no per-request Postgres identity, so
  authorization is enforced entirely in the API layer (verified real,
  not cosmetic). Enabling real per-user RLS needs new session-identity
  plumbing this app doesn't have yet; investigated 2026-09-06 and
  presented to the user, not yet decided on — see `decisions.md`'s
  Database access control entry for the validated path if/when this is
  picked back up.
- CI on `main` was briefly red on 2026-09-07 (since PR #38's merge) — an
  `npm ci` `ERESOLVE` conflict (`@types/node` pinned too old for
  `vitest@5`) and an unsorted-import `ruff` failure, neither caught
  before that merge (both slipped through because a local `npm install
  --legacy-peer-deps` doesn't enforce the same strict peer resolution
  `npm ci` does). Found while opening PRs #39–42 above — every one
  failed CI in under 20 seconds on these same two issues, not their own
  diffs. **Fixed and merged (PR #43)** — CI on `main` is green again.
  Before this, CI on `main` had been green since PR #29 (2026-09-05)
  caught a real `frontend-lint-and-build` failure before merge (ESLint's
  `react-hooks/set-state-in-effect` rule on a `localStorage` read; fixed
  with `useSyncExternalStore`, see `decisions.md`'s UI styling entries),
  and backend CI had been green since a `pytest` import bug fixed
  2026-08-31. `frontend-lint-and-build` has run `npm run test` (Vitest)
  since 2026-09-06.
