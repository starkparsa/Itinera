# Progress — Itinera

Dated diary: what happened, what changed, what should happen next.
Consolidated 2026-09-02 from what had been ~21 individual files under
`docs/sessions/`. Newest first. For the decisions this history produced,
see [`decisions.md`](decisions.md); for where things stand right now, see
[`STATUS.md`](STATUS.md).

## 2026-09-09 — A traveler's usual trip length now defaults new trips, same soft-instruction pattern as an existing trip's length

`UserProfile.typical_trip_length_days` (collected at onboarding) existed
in the schema but was never read anywhere -- a brand-new trip request
with no duration language of its own ("a trip to Lisbon") was left
entirely to the model's own generic guess (`META_INSTRUCTIONS`'s "a
week" = 7 heuristic), ignoring a real preference the traveler had
already stated.

Closed with the exact same mechanism `_infer_trip_meta` already uses for
`previous_total_days` (an already-established trip length within a
conversation) -- a soft instruction folded into the meta prompt, never a
hard override: the latest request's own duration language ("a week in
Lisbon", "10 days") still wins. Priority order, most to least specific:
`requested_days` (explicit UI field) > `previous_total_days` (this
conversation already has a generated trip) > `typical_trip_length_days`
(the traveler's general profile default) > the model's own free
estimate. The profile default only applies when there's no
already-established trip in the conversation to anchor to instead.

`routers/trips.py`'s `_handle_new_or_edit_trip` (already querying
`UserProfile` for `user_profile_note`) now also forwards
`profile.typical_trip_length_days` straight through
`generate_itinerary`/`_infer_trip_meta` -- no new query, no schema
change. 5 new tests (3 in `test_llm_service.py` covering the new note
and the priority-over-typical-length case, 2 router-level in
`test_trips_router.py`) -- backend suite 407 → 412. Shipped in the same
PR as the Q&A personalization fix above, since both are the same
"profile data that already existed wasn't reaching every prompt it
should" pattern.

## 2026-09-09 — Onboarding preferences reach conversational Q&A too, not just itinerary generation

Found while explaining the app's LLM-stabilization prompts to the user:
`user_profile_note` (pace, budget, interests, dietary/accessibility
needs from `UserProfile`) was threaded into itinerary generation from
day one, but `routers/trips.py`'s question branch never built or passed
it to either `llm_service.answer_question` or `agent_service.
answer_question_with_tools` — a real, live gap, not a hypothetical one:
"suggest somewhere to eat" or "what should I pack" got answered with no
awareness of a traveler's own stated dietary needs or budget.

Closed with no new mechanism: both functions gained a `user_profile_note`
parameter, appended to their system prompts with the same "personalize
with this, don't treat it as fact, don't invent beyond it" caution
`_generate_chunk` already applies to the same note. `_handle_question`
now looks the profile up via `conversation.user_id` directly (no `user`
parameter needed through the call chain) and passes the note to both the
tool-calling loop (tried first) and its plain fallback, so whichever one
actually answers has it.

5 new tests (2 in `test_llm_service.py`, 2 in `test_agent_service.py`, 1
router-level integration test in `test_trips_router.py` asserting the
note reaches both call sites with a real `UserProfile` row and a real
posted message) — backend suite 402 → 407.

## 2026-09-08 — Installable-shell PWA shipped

Picked "installable shell only" over "offline trip viewing" (the two
options scoped and presented before building) — a manifest, three icon
sizes generated from the existing 512×512 app icon (including a
`maskable` variant), and a service worker that cache-first-serves only
five static assets, passing every page/API request straight to the
network untouched. Registered via a small `PwaRegister` client
component after `window.load`, so it never competes with the chat UI's
own first paint. `layout.tsx` also gained Safari's separate
`appleWebApp` opt-in, since Safari ignores `manifest.webmanifest`
entirely.

Verified live in the real dev frontend (`link[rel="manifest"]` resolves,
one active service-worker registration scoped to `/`), not just built.
4 new tests for `PwaRegister` (immediate registration, waits for `load`
when the page is still loading, renders nothing and never throws with no
`serviceWorker` support, swallows a rejected registration) — frontend
suite 39 → 43. `tsc --noEmit`/`eslint` clean.

Deliberately doesn't cache trip/itinerary data or anything per-user —
that's "offline trip viewing," a distinct, larger scope with its own
cache-invalidation/sync design questions, not attempted here. See
`decisions.md`'s PWA entry.

## 2026-09-08 — Postgres row-level security actually shipped (a second, non-bypass role)

Picked back up the RLS investigation paused 2026-09-06 (see
`decisions.md`'s "Database access control (RLS)" entry for the full
before/after). Built the previously-validated plumbing exactly as
scoped — a SQLAlchemy `after_begin` hook, `auth.get_current_user`
setting the identity on `session.info`, an Alembic migration enabling +
forcing RLS with `user_id`-keyed policies on 6 tables and an
`EXISTS`-subquery policy for 3 FK-hop tables — applied it to the real
dev database, and ran a direct two-temporary-user verification script
before trusting it. It did nothing: every row stayed visible under every
identity, including none at all.

The real cause was worse than the original write-up assumed: Neon's
default project-owner role (`neondb_owner`, this app's only role) has
`BYPASSRLS` set directly — unconditional, and `FORCE ROW LEVEL SECURITY`
has no power over it at all (`FORCE` only overrides ownership-based
bypass). Rolled the migration back immediately rather than leave
non-functional policies that look like protection but aren't.

Presented three real options to the user with honest pros/cons: revoke
`BYPASSRLS` from the existing role directly (simplest, but a security
attribute change on the project's primary role — correctly refused to
run that myself, `ALTER ROLE` was blocked by the permission classifier
and rightly so); a second, lower-privileged role for runtime queries
(more moving parts, but touches nothing existing); or shelve it again.
User chose the second role.

Created `itinera_app` (no `BYPASSRLS`, no `SUPERUSER`), granted table/
sequence access plus `ALTER DEFAULT PRIVILEGES` (so future migrations'
tables don't need a manual grant), wired a new `APP_DATABASE_URL` env
var that `database.py` falls back to `DATABASE_URL` when unset (sqlite
tests and any not-yet-provisioned environment stay exactly as before).
Re-applied the migration (via the still-owner `DATABASE_URL`), re-ran
the same isolation script against the new role: cross-user read blocked,
cross-user write rejected via the `WITH CHECK` clause, no-identity-set
sees nothing, and the FK-hop case (`itinerary_items` via `trips`) also
correctly isolated. `users` itself stays deliberately unprotected by
RLS — `/auth/register`/`/auth/login` look a row up by email before any
identity exists, which is what "login" means and can't be reconciled
with a per-user policy without a third role scoped just to those two
endpoints; not justified given that table's existing protections
(unique constraints, bcrypt, exact-match lookups) were already real.

Backend suite (402 tests, sqlite) unaffected throughout — RLS is a
Postgres-only concept the test suite never touches. Verified live
against the real dev database directly, not via pytest.

## 2026-09-08 — Race condition in profile get-or-create fixed (PR #53)

The race flagged (not fixed) during Phase 1 of the auth work below —
`_get_or_create_profile`'s SELECT-then-INSERT had no protection against
two concurrent requests for the same brand-new user both passing the
SELECT before either committed, newly exposed by the credentials flow's
faster client-side redirect to `GET /profile`. Flagged via `spawn_task`
to a peer session (`kind-boyd-57d162`) rather than fixed inline at the
time, since it was unrelated to the auth work in progress.

Checked that peer session's worktree directly rather than assuming it
had finished or guessing at the fix: found a correct, verified,
uncommitted diff sitting in its git state. Rather than wait on that
session to commit/push, reapplied the identical diff onto a fresh branch
off current `main` — deliberately not touching the peer session's own
worktree/branch, to avoid any interference with its independent state —
then messaged that session afterward to say the gap was already covered,
avoiding duplicate work.

**Fix**: the losing request's `db.commit()` now runs inside a
`try/except IntegrityError` — on the unique-constraint violation it
rolls back its own failed insert and re-queries for the winning
request's row instead of letting the `IntegrityError` propagate as a
500. One new test (`test_get_or_create_profile_recovers_from_concurrent_insert_race`)
simulates the race directly: a second `SessionLocal()` commits the
winning row first, then the original session's `commit()` is patched to
raise the real `IntegrityError` shape (`user_profiles_user_id_key`) so
the recovery path is exercised without needing genuinely concurrent
threads. Verified against the real dev Postgres schema's actual unique
constraint name.

## 2026-09-07/08 — Real email/password auth added, Facebook built then removed, an audit-driven hardening pass (PRs #47, #48/closed, #49, #50)

A fully-detailed three-phase brief (Google + Facebook + email/password,
one shared session/database/onboarding flow) arrived with its own
proposed schema (a separate `sessions` table, a `login_attempts` table)
and build order. Researched the real architecture first — Auth.js JWT
sessions, no backend session store — and asked three clarifying
questions before writing anything: reuse Auth.js's session or build a
parallel one (user: reuse it); build order (user: email/password first,
Facebook after); get Facebook credentials first or build the code
anyway (user: build now, get credentials separately).

**Phase 1 — email/password (PR #47).** `password_hash` column
(nullable, same shape as `google_sub`), `password_auth.py` (bcrypt
directly), `POST /auth/register`/`POST /auth/login` (rate-limited
5/minute, one generic "incorrect email or password" for both wrong-
password and unknown-email, a distinct honest message for a Google-only
account). `get_current_user` gained a `provider` JWT claim (default
`"google"`, backward-compatible) — `"credentials"` looks up by this
app's own internal `User.id` directly, never auto-provisioned, since a
password account can only be created via `/auth/register`. Frontend: a
`Credentials` provider in `auth.ts` bridging to the same backend
endpoint, `LoginCard.tsx` wired for real with client + authoritative
server-side validation. Two real bugs found and fixed: the submit
button's `<form onSubmit>` never actually fired (this app's `Button`
doesn't reliably forward `type="submit"` through its `@base-ui/react`
primitive — fixed via `onClick`, matching `OnboardingFlow.tsx`'s
convention), and a password-strength hint nested inside its `<label>`
polluted the label's accessible name (fixed by moving it to a sibling
`aria-describedby` span). Verified against the real dev Postgres
database: real signup → logout → re-login → wrong-password rejection,
driven directly via the browser's JS console since the automated
`computer` tool's coordinate clicks were unreliable against this
React-controlled-input form. Found (but didn't fix — flagged via
`spawn_task` instead, since it's unrelated to auth) a real pre-existing
race condition in `profile.py`'s get-or-create, newly exposed because
the credentials flow's client-side redirect reaches `GET /profile`
faster/more concurrently than Google's full-page OAuth round-trip ever
did.

**Phase 2 — Facebook (PR #48), built then removed.** Added
`facebook_id` (same nullable/unique/indexed shape as `google_sub`),
generalized `get_current_user` with a `"facebook"` branch, and closed a
real latent gap found while generalizing: a brand-new OAuth identity
whose email already belongs to a different account now gets a clean
401 instead of silently linking or crashing on the `users.email` unique
constraint — applied to both the Google and Facebook branches (existed
for Google alone before, just unreachable until Phase 1 gave email a
second claimant). Deliberately **not** auto-linking accounts by email —
this app's email/password signup has no verification step, so silent
linking would hand an attacker who pre-registered a victim's email
access to whatever account a later real OAuth login attaches to it.
Verified with a real browser click-through: the Facebook button
correctly redirected to Facebook's own OAuth endpoint, failing only on
"Invalid App ID" since no real Facebook app existed yet. Fully working,
then the user decided against pursuing Facebook at all — PR #48 closed
unmerged, its branch deleted; PR #49 removed the now-pointless UI
placeholder (button, glyph, toast test) that had existed since the
original login redesign mockup.

**Hardening pass (PR #50), from a second brief re-litigating the same
build.** This one explicitly demanded an audit-before-building step;
followed it literally — checked the actual code against its own
checklist (schema, hashing, sessions, rate limiting, validation, error
patterns) before writing anything, and found almost everything already
existed. Closed the two real gaps: auth-event logging (signup/login
success and each distinct failure reason, asserted in tests to never
include the password) and a small static common-password blacklist
(catches e.g. `Password1!`, which satisfies every character-class rule
but is a first guess in any real attack). Declined a third candidate —
shortening Auth.js's session cookie from 30 days toward the brief's
1-24h guidance — since that setting is shared with Google logins too
and the real backend-facing JWT already expires every 60 seconds
regardless.

**Verified across all three**: backend suite 396 passed after Phase 1
(PR #47), unchanged through Facebook's build-then-close since PR #48
was never merged, then 401 after the hardening pass's 5 new tests
(PR #50); frontend suite 34 → 40 (Phase 1) → 39 (PR #49 removed
Facebook's one toast test, unaffected by the backend-only hardening
pass). `tsc --noEmit` and `eslint` clean throughout.

**A real gap found while documenting this, not while building it**:
Facebook's migration (`facebook_id`) had been applied and round-tripped
against the live dev database while PR #48 was open, but closing that
PR unmerged left the real dev database pointing at an Alembic revision
(`a1f3c9d02b7e`) that no longer exists anywhere in the repo — the file
was on the deleted branch. Any `alembic` command against that database
would have failed outright from that point on. Caught this while
writing up the migration history for this entry (not from a test —
`pytest` uses a fresh SQLite schema per run, so this was invisible to
the whole suite). Fixed directly: dropped the orphaned `facebook_id`
column and its index, then stamped `alembic_version` back to
`0668d9be3ecf` (Phase 1's real head) — verified with `alembic current`
and a full backend suite re-run afterward. *Lesson: closing a PR that
already touched a live database needs the database rolled back too,
not just the branch deleted — the two aren't the same action.*

## 2026-09-07 — Login page redesigned end to end (PR #45)

Requested twice with the same wrong premise: a traditional email/
password login page with a "Sign Up" CTA, then a full redesign brief
adding Facebook login, "Forgot Password?", wrong-password error states.
Both times, checked the real code first (`backend/app/auth.py`,
`login/page.tsx`) before designing anything — this app has only Google
OAuth, no password system, no separate signup flow to link a button to.
Asked the user directly each time rather than silently building a
fictional second auth flow or reversing that architecture decision.

**Pass 1 — copy only.** One line under the existing button: "New here?
Signing in with Google creates your account automatically." Shipped,
verified in the Browser pane across viewports/color schemes.

**Pass 2 — full visual redesign, mockup first.** Built and published a
design-exploration artifact ("Dusk City Login") showing a Login/Signup
chip-tab toggle, Google/Facebook/email options, all requested error and
loading states, and a spec sheet (color tokens, type scale, component
inventory) — explicitly labeled as not wired to a backend. Approved,
then integrated for real: new `LoginCard.tsx` (client component) +
`login/actions.ts` (splits the real Google server action out of the
now-server-only `page.tsx` so the client component can call it).
Facebook and email/password got full visual treatment but every
interaction (click, submit, forgot-password) honestly toasts "isn't
available yet" — no fake success, no fabricated "wrong password" error.

**Pass 3 — background, on request.** Added a "Dusk City" gradient +
inline SVG skyline (this app's own indigo/copper hues, no photo asset)
to the mockup first, got it approved, then ported the same CSS/SVG into
the real page. Deliberately fixed regardless of light/dark mode — a
brand moment, not a themed surface.

**Declined**: a follow-up ask to swap that background for live Pexels
photos. Technically buildable (this app already has a working Pexels
integration for trip photos), but would need a new *public*
unauthenticated backend endpoint (`/login` has no session yet) plus a
real third-party dependency on the one page that should never be
allowed to break. Presented the tradeoff, user chose to keep Dusk City.

**Two real bugs, caught by actually testing, not eyeballing:**
- Opened the integrated page at a short viewport and found the card's
  overflow content (email form, gamification hint, switcher line) was
  completely unreachable — this app's `globals.css` sets
  `overflow: hidden` on `html`/`body` for `ChatApp`'s own single-scroll
  contract, and that rule doesn't know `/login` is a different kind of
  page. Fixed by giving `/login` its own `h-screen`/`overflow-y-auto`
  scroll region.
- Wrote `LoginCard.test.tsx` (10 tests) and two failed in a way that
  looked like a test bug at first: the email-submit and invalid-email
  tests couldn't find the expected validation text at all. Traced it to
  the submit `Button` never actually triggering the wrapping
  `<form onSubmit>` — this app's `Button` wraps a `@base-ui/react`
  primitive, and `type="submit"` apparently doesn't reliably forward
  through it to a real native submit control. Fixed by dropping the
  `<form>` and wiring the button via `onClick` directly, matching
  `OnboardingFlow.tsx`'s own established convention (checked: every
  save/continue action there already avoids native form submission the
  same way). All 10 tests passed after the fix; full suite stayed green
  (34 passed) throughout.

**Verified**: full frontend suite (34 passed), `tsc --noEmit` clean,
lint clean, and manual checks in the Browser pane — desktop/mobile
viewports, light/dark color schemes, chip-tab toggling, the Facebook
toast, and the scroll fix (confirmed `scrollHeight > clientHeight` and
that previously-unreachable content was actually reachable).

## 2026-09-07 — Four follow-on features built (PRs #39–42), plus a broken-main-CI fix (PR #43)

Planned as one pass covering four gaps flagged after 2026-09-06's
onboarding personalization session (below), built and verified as four
isolated branches/PRs, in build order, then merged the same day —
PR #43's CI fix first, then #39/#40/#41, then #42 last (its migration
chained after #40's). Each branch was updated with `main` and its own
CI reverified green immediately before merging.

**PR #39 — onboarding chip/tag visual polish.** New
`components/ui/toggle-chip.tsx`: a real, visually-hidden
`<input type="checkbox"|"radio">` styled via a sibling `<span>` through
Tailwind `peer-*` selectors, replacing five `<select>`s and the
interests checkbox group. Verified visually in the Browser pane against
a temporary local debug route (removed before commit) — clicked through
single-select exclusivity and multi-select toggling directly, not just
trusted the CSS. `country_region` deliberately kept as a plain
`<select>` (5 options + a conditional "Other" branch — a select still
handles that better than a chip would).

**PR #40 — Events Trip Hub card.** `find_events` had worked
conversationally since 2026-09-04 but had no UI. Chose a live per-trip
fetch cached on `Trip.events_json`/`events_fetched_at` with a 6h TTL —
mirrors `weather_service.py`'s existing pattern exactly, deliberately
not a new `SavedPlace`-style table (this is one read per page load, not
something accumulated across a chat loop). New `events_service.py`,
`schemas.EventOut`, a third card in `TripHubPanel.tsx`. Verified the
migration both directions (upgrade + downgrade) against an isolated
pre-migration SQLite DB, same discipline as every migration this project
has shipped.

**PR #41 — auth-testing gap closed with documentation, not new test
code.** Investigated the "no real signed-in click-through" item and
found it was two different claims: `backend/tests/conftest.py` already
fully mocks auth for the automated suite (nothing to build there); the
real gap is a genuine browser OAuth click-through, which this app's BFF
architecture (FastAPI never talks to Google) and lack of any E2E
framework make disproportionate to automate. Wrote
`docs/manual-auth-testing.md` as a human-run runbook instead, plus one
legitimate small gap-filler: a real unit test on `mintBackendJwt.ts`
(hit a jsdom/`jose`-webapi cross-realm `Uint8Array` incompatibility
verifying it — fixed with a `// @vitest-environment node` pragma on that
one test file, since it has no actual DOM dependency).

**PR #42 — gamification (passport stamps + tiered badges), 0% built
before this.** Two new tables (`UserStats`, `UserAchievement`), new
`stats_service.py`/`gamification_service.py`/`passport_service.py`, new
`GET /gamification/passport`, a new `PassportBadges.tsx` section on the
existing `/profile` page. Two real bugs found and fixed during
implementation, not just planned around:
- `_handle_new_or_edit_trip` inserts a fresh `Trip` row on *every*
  `new_trip` and `edit_trip` turn, not just new trips — without
  accounting for that, gamification's trip counts/badges/stamps would
  have inflated every time someone conversationally tweaked an
  already-planned trip. Fixed with a new `Trip.is_edit` column, set from
  the already-classified intent at creation time.
- Built the stamp-accent UI, took one look in the Browser pane, and the
  tiles were pastel-light regardless of the OS dark-mode setting.
  Traced it to `globals.css`'s `@custom-variant dark (&:is(.dark *))` —
  this app's dark mode is `prefers-color-scheme`-driven, not a
  `.dark`-class toggle, so Tailwind's `dark:` utility prefix has *never*
  actually applied anywhere in this codebase (confirmed several
  pre-existing, silently-dead `dark:` classes already sitting in
  `TripCard.tsx`/`TripView.tsx`/shadcn's generated `badge.tsx` etc.).
  Fixed properly for the new work: 8 named `--stamp-*` CSS custom
  properties following the exact pattern `--chat-assistant-*` already
  established (light values in `:root`, dark overrides in the existing
  media-query block, registered in `@theme inline`). Re-verified in the
  Browser pane under both `resize_window`-emulated light and dark
  `colorScheme` — confirmed distinct, legible tiles in both.
Also simplified the XP design mid-build: rather than incrementing
`xp_points` at a trip-generation hook (the originally-sketched, unbuilt
design), `evaluate_and_award` *sets* it from real trip count on every
`GET /gamification/passport` call — removes an entire class of
double-award-on-repeated-call risk for free, at no cost to the feature.

**PR #43 — main's CI was found broken while opening the four PRs
above.** Every one failed CI in under 20 seconds — too fast to be a real
test failure. `gh run list --branch main` confirmed `main` itself had
been red since PR #38 merged: an `npm ci` `ERESOLVE` conflict
(`@types/node` pinned to `^20`, but `vitest@5.0.0` peer-requires
`^22`/`>=24` — apparently never hit locally under
`npm install --legacy-peer-deps`, only under CI's strict `npm ci`) and
an unsorted-import `ruff` failure in `tests/test_trips_router.py`.
Bumped `@types/node` to `^22` (matching `ci.yml`'s own Node version),
regenerated `package-lock.json` with a real `npm install`, verified a
real `npm ci` now succeeds against it (previously failed), and
`ruff --fix`'d the import block. Neither issue was introduced by any of
the four feature PRs — both predate this session entirely.

**All five PRs merged same-day.** One real merge conflict surfaced along
the way: PR #42's `models.py` conflicted with PR #40's, since both add
new `Trip` columns near the same spot (`events_json`/`events_fetched_at`
vs. `is_edit`) — resolved by keeping both, re-verified (374 backend
tests, 24 frontend tests, a single clean Alembic head) before merging.
**What's left, honestly:** the visual chip design, stamp accent colors,
and badge tier mapping are all first-pass choices, not a separate
design-review round — worth a quick look now that they're live, before
considering them final.

## 2026-09-06 — Onboarding personalization built end to end

Design first (three rounds of mockups, research-informed — see
`docs/design-references.md`), then real code, built incrementally with a
review gate after each step rather than as one large change:

**Step 1 — data model.** `UserProfile` (1:1 with `User`, mirrors
`GoogleCalendarCredential`'s shape), one migration. Verified by applying
it against a simulated pre-migration database, not just by reading it.

**Step 2 — `GET/PUT /profile`, `POST /profile/onboarding/skip`.** Caught
one real thing during review: the JSON encode/decode for the two
list-valued fields was duplicated across two functions — collapsed into
one `JSON_LIST_FIELDS` tuple before calling the step done.

**Step 3 — wired into `generate_itinerary`'s prompt.** Same append
pattern `answer_question`'s `agent_context` already uses. Caught a real
regression during verification: an existing test asserted the *exact*
kwargs `generate_itinerary` is called with, and the new parameter broke
it — fixed the assertion rather than loosening it.

**Step 4 — `OnboardingFlow`.** A status report claimed an "Account
details form (name, mobile, DOB, country)" was built and confirmed; it
wasn't — re-checked directly against `OnboardingFlow.tsx`'s actual step
list and `UserProfile`'s actual columns before accepting that claim, and
corrected the record rather than planning on top of it. Once corrected,
the fields were built for real — but only after their purpose was
committed to first (SMS reminders for `mobile_number`, age-bracket
personalization for `date_of_birth`), not collected speculatively.

**Then a "leave nothing behind" pass**, closing every gap raised along
the way: real phone/DOB validation (client courtesy + authoritative
server-side Pydantic validators), consent copy on the sensitive fields, a
hand-built toast system (`components/ui/toast.tsx` — this app's first
ambient-notification primitive, `role="status"`/`aria-live="polite"`), a
real `/profile` page reusing `OnboardingFlow` in a new `mode="edit"`
(closing a real dead end — `/profile` was referenced in a schema
docstring but unreachable from anywhere in the app), and a frontend test
framework stood up from scratch (Vitest + React Testing Library — nothing
in this frontend had automated tests before today), with 12 tests
covering the new form/validation/toast logic. Wired `npm run test` into
`frontend-lint-and-build` in CI — verified first under a clean `npm ci`
in an isolated directory, since the local dev install had needed
`--legacy-peer-deps` and CI's strict install needed checking separately.

**Real bug found from a user screenshot, not a code review**: every
`<select>` in the onboarding form was rendering nearly-invisible
light-gray-on-white options in dark mode. Root cause: a `<select>`
inherits the page's dark-mode text color, but its native OS dropdown
popup still renders on a light background — `color-scheme` isn't
inherited into that popup the way normal CSS is. Fixed with one shared
utility (`[color-scheme:light]` on the field class every select already
used), confirmed as a real compiled CSS rule in the production bundle
(not just present in source) by grepping the built `.next` output, plus a
regression test.

**Verified, not assumed, throughout**: 345 backend tests passing
(324 → 345 across the whole build), 12 new frontend tests, `tsc`/`eslint`
clean, a real production `next build`, and both dev servers actually
started (not just imagined) to confirm live: the backend's own Swagger UI
lists all three `/profile` endpoints, `/`/`/trips`/`/profile` all
correctly redirect an unauthenticated request to `/login`, and a real
unauthenticated `GET /profile` returns a genuine 401 with a clear
message.

**What's still genuinely open, not silently dropped**: SMS sending itself
(needs an external provider, evaluated against a real free tier first —
same posture as the still-unverified Travelpayouts/Aviasales flight-data
question); the visual chip/tag polish pass on the onboarding fields
(currently plain `<select>`/checkboxes); and a real signed-in
click-through of the whole flow, which stops at the OAuth handshake
itself since that needs the user's own Google credentials. See
`decisions.md`'s new Onboarding personalization entry for the full
reasoning behind every choice above.

## 2026-09-06 — Secrets/RLS security pass (PR #35, #36)

Four back-to-back security-focused requests, each investigated directly
against source before any code changed:

**Frontend secrets audit — clean, nothing to fix.** Checked for
`NEXT_PUBLIC_*` vars (zero), hardcoded keys/static `Authorization`
headers (none — the only `Bearer` sites mint a fresh per-request JWT
server-side), direct frontend-to-third-party calls (none — every
`fetch()` targets the app's own backend), and secret scoping (`AUTH_*`
vars read only in `server-only`/`"use server"` files, never in any of the
12 `"use client"` files). `next.config.ts` has no `env:` re-export block
either. The architecture already does everything the request asked for.

**Git-history secret audit — clean (PR #35).** `git log --all` across
every branch, full history: no real `.env` file, and no hardcoded
Google/Groq/AWS-key-shaped or private-key-header string, was ever
committed at any point. Every revision of every tracked `.env.example`-
style file held only placeholders. Found and fixed one real gap while
checking: root `.gitignore`'s bare `.env` line only matched that exact
filename, leaving `.env.local`/`.env.production`/`backend/.env.local`
uncovered outside `frontend/.gitignore`. Broadened to `.env.*` (with
negations for the two tracked example files) plus added common
secret-file shapes (`*.pem`, `*.key`, `*credentials*.json`, etc.) not yet
ignored at the root. No file had ever actually leaked — this closed a
hole before it could be used.

**Database key check — not applicable.** Asked to confirm the frontend
only uses a Supabase-style anon/public key, never a service-role key.
This app has no Supabase and no client-side database access of any kind
— Postgres (Neon) is reachable only through the backend's own
`DATABASE_URL`, read exclusively server-side. Nothing to move.

**Row-level security — investigated, not built.** See `decisions.md`'s
new "Database access control (RLS)" entry for the full reasoning: this
app has a single Postgres role for the entire backend and no per-request
Postgres identity, so naively enabling RLS would either do nothing
(table owner bypasses it) or break every request (forcing it with no
session-variable mechanism in place) — plus a genuine chicken-and-egg
problem looking up a user's own row by `google_sub` before its `id` is
known. Presented the real blockers and the validated path to a proper
fix; user paused mid-decision rather than picking a path, so no schema or
code change was made. Authorization stays enforced at the API layer only,
same as today.

## 2026-09-06 — Fix: `/login` shown to already-authenticated users (PR #36)

Bug report: a signed-in user hitting `/login` directly (typed URL, stale
bookmark, transient redirect) saw the sign-in form and stayed there,
instead of bouncing to the app. Root cause: `app/login/page.tsx` had no
session check at all — always rendered the form regardless of auth
state. Fixed by making it an async server component that calls `auth()`
and redirects to `/` when a session exists, mirroring
`app/(chat)/layout.tsx`'s existing check in the opposite direction.
`tsc`/`eslint` clean; verified live in the user's real, already-signed-in
Chrome session (not just the sandboxed preview, which has no session of
its own) — navigating to `/login` now lands on `/` directly, form never
renders.

## 2026-09-06 — Split `generate_trip` and extracted `ChatShell.tsx` hooks (PR #33)

The two "deliberate follow-ups" the codebase-cleanup pass below flagged
but didn't touch — both deferred at the time as too risky to bundle with
the zero/low-risk cleanup. Planned properly this time: two Explore passes
(one per file, gathering exact line ranges/shared-state/cross-concern
dependencies) feeding a Plan pass, then every claim in that plan
double-checked by directly re-reading the actual current files before
writing a line of code — not taken on an agent's word alone. Both are
pure structural refactors; neither changes behavior.

**Backend**: `routers/trips.py`'s `generate_trip` (~350 lines, three
inline reply paths: off-topic, question, new/edit trip) split into three
module-level helpers matching the file's own existing convention
(`_persist_found_places`, `_build_conversation_context`, etc.):
`_handle_off_topic`, `_handle_question`, `_handle_new_or_edit_trip`.
`generate_trip` itself is now the shared preamble (quota check,
conversation lookup/creation, intent classification) plus a 3-line
dispatch. Extracted one branch at a time, running
`pytest tests/test_trips_router.py -k <branch>` after each before moving
to the next, then the full suite — 324/324 pass, `ruff check` clean.

**Frontend**: `ChatShell.tsx` (578 lines, ~6 separable concerns per the
2026-09-05 entry below) split into three new hooks, extracted in order
from least to most coupled: `hooks/use-sidebar-open.ts` (self-contained,
no cross-hook dependencies), `hooks/use-scroll-restore.ts` (needs only
primitives `ChatShell` still owned directly at that point), and
`hooks/use-conversation-loader.ts` (the largest and most coupled —
conversation loading/caching *and* the pending/error state machine kept
together deliberately, since `loadConversation` writes `pending`/`error`
directly and splitting them would've meant passing setters bidirectionally
between two hooks for no real benefit). Every load-bearing behavior from
the 2026-09-05 fix — the Strict-Mode generation-counter guard, the
module-scope caches (not hook-internal state, or they'd stop surviving
remounts), `useSyncExternalStore` for the sidebar, `useLayoutEffect` for
scroll timing, the `skipCache`+`showLoading` two-flag call shape — moved
verbatim, not reimplemented. `ChatShell.tsx` is now 349 lines of glue +
JSX. `ChatShellContext`'s public contract is unchanged, so
`OpenConversation.tsx` and all three page files needed zero edits.
`tsc`/`eslint` clean, full `next build` succeeds, dev server smoke-tested
with no console errors.

**Known gap**: no frontend test runner exists at all in this repo, so the
real regression net for the frontend half is `tsc`/`eslint`/`build` plus
a written manual checklist (chat-switch flash, scroll restore per
conversation, Strict Mode rapid-click safety, delete clearing both
caches). **Closed 2026-09-06**: user ran the checklist themselves against
a real signed-in session (the agent still can't complete Google OAuth
itself) and confirmed everything works correctly.

## 2026-09-05/06 — Codebase-cleanup audit and cleanup (PR #31, #32)

**PR #31 — a way to actually share a running instance.** CI already
builds and publishes `ghcr.io/starkparsa/itinera-{backend,frontend}:latest`
on every merge to `main` (confirmed live: both pullable with no login, via
a raw anonymous-token manifest fetch, not assumed) — but nobody without
the repo's full dev setup could use that fact. Added
`docker-compose.share.yml` (pulls those images instead of building from
source) and `.env.share.example`, defaulting `DATABASE_URL` to a local
SQLite file so a friend needs nothing but Docker and one free Gemini key.
Documented in README as a third "Option C" alongside the existing
Docker-Compose-from-source and no-Docker paths.

**PR #32 — full-codebase maintainability audit, then acted on the safe
findings.** Three parallel Explore passes (backend, frontend, repo-root/
config), every actionable finding verified directly against the real
files before acting — not treated as ground truth from an agent's report
alone. Overall finding: the codebase was already unusually disciplined;
this was a short, low-risk list, not a sprawling one. Confirmed
intentional and deliberately left alone: the MySQL/`legacy-mysql`/
`pymysql`/`migrate_to_neon.py` rollback bundle (tracked by
`docs/deployment-readiness.md` with an unmet removal condition), the
`AGENT_TOOL_CALLING_ENABLED` currency kill-switch, `tools.TOOL_SCHEMAS`
(exercised by a real test), and unused shadcn sub-exports (cost nothing
at runtime, trimming them fights the project's own re-sync workflow).
Shipped:

- Deleted `frontend/src/app/api/trips/[tripId]/calendar/route.ts` — a
  dead proxy route left over from before the two-button calendar export
  UI was merged into one "Export Plan" button (2026-08-26 entry below).
  The backend `.ics` endpoint it proxied stays; only the frontend wrapper
  was unreachable.
- Untracked `skills-lock.json` (`git rm --cached`) — committed before its
  own `.gitignore` entry was added, directly contradicting that entry's
  stated intent.
- Reworded stale comments in `main.py`/`models.py` still naming MySQL as
  the live database, post the 2026-08-29 Neon migration.
- Forwarded `GOOGLE_PLACES_API_KEY`/`PEXELS_API_KEY`/`TICKETMASTER_API_KEY`
  into both `docker-compose.yml` and `docker-compose.share.yml` — the same
  class of gap `docker-compose.yml`'s own comments already recorded once
  for `GROQ_API_KEY`, now recurring for three newer live, key-driven
  features that had shipped since that fix.
- Extracted `gemini_client.to_contents()` (identical chat-history-to-
  `Content` conversion had been duplicated in `llm_service.py` and
  `agent_service.py`) and `networkErrorMessage()` in `frontend/src/lib/
  backend.ts` (the same catch-block ternary hand-rolled 4 times).
- Removed two dead re-exports in `google_calendar.py` (`InvalidToken`,
  `HttpError` — neither used anywhere, and `routers/trips.py` imports
  `HttpError` directly from `googleapiclient.errors` instead).
- Migrated all 5 pydantic v1-style `class Config: from_attributes = True`
  blocks in `schemas.py` to v2's `model_config = ConfigDict(...)`.

Deliberately *not* touched, flagged for their own later passes instead:
splitting `generate_trip` and extracting `ChatShell.tsx`'s hooks — see
the entry above this one for where those actually landed, one session
later.

## 2026-09-05 — Chat-switch "full reload" bug: shared layout + server-side conversation seeding (PR #29)

User-reported: switching chats in the sidebar looked like a full page
reload every time — a skeleton flash, scroll position resetting. Took
several wrong turns before finding the real cause, worth recording
honestly since each one seemed plausible and each one was live-tested,
not assumed:

1. **sessionStorage for scroll position** — implemented, reported "not
   working." Verified the restore logic itself was correct via an
   isolated React test harness (mount/unmount simulation matching real
   navigation) before suspecting the storage layer; user's browser
   (Brave, visible in a screenshot) plausibly blocks/throws on
   `sessionStorage` under some shield settings.
2. **In-memory `Map` instead of sessionStorage** — same "not working"
   report. Root cause found by inspecting the actual render sequence:
   `ChatApp` always started render with empty `messages`/
   `activeConversationId`, filled in by a `useEffect` — which only fires
   *after* first paint, guaranteeing one blank frame on every remount no
   matter how fast the cache lookup was. Fixed with lazy `useState`
   initializers seeded from the cache instead. Still reported "not
   working."
3. **The actual break came from a user-supplied DevTools Network-tab
   screenshot**: all requests were type `fetch`, never `document` (ruling
   out a real browser reload), but each conversation id showed **two
   identical `backend.ts` fetches** back to back — the signature of React
   Strict Mode's dev-only double-invoke of effects. This looked like the
   answer, but wasn't the whole one.
4. Two Explore agents dispatched in parallel confirmed the bigger,
   real issue: `/` and `/trips/[tripId]` shared **no layout** — both were
   direct children of the bare root `app/layout.tsx`, so every switch
   between them fully remounted the entire chat UI (sidebar included) and
   separately re-ran `auth()` + fully uncached (`cache: "no-store"`)
   backend fetches, each re-minting a JWT via `mintBackendJwt()`, before
   the page could even render.
5. Fixed with a Next.js route group, `app/(chat)/layout.tsx`, shared by
   `/` and `/trips/[tripId]` — App Router does not remount a shared layout
   on navigation between sibling routes under it, only the page segment
   that actually changed. `components/ChatApp.tsx` (546 lines: sidebar,
   message log, composer, all state) was split into `ChatShell.tsx`
   (moved into the persistent layout, effectively unchanged logic) and a
   tiny `OpenConversation.tsx` bridge each page renders to tell the shell
   which conversation to open, via a new `ChatShellContext`.
6. **User re-tested against a genuine production build**
   (`npm run build` + `node .next/standalone/server.js`, since this
   project's `output: "standalone"` config means plain `next start`
   doesn't work) and still saw "double loading" — which conclusively
   ruled out Strict Mode (dev-only) as a real cause. A second Network-tab
   screenshot showed the actual remaining shape: each chat switch did two
   genuinely separate, slow (~1-2.4s each) round trips in sequence — the
   page's own `getTrip()` (server-side), then a *second*, separate
   client-initiated `getConversation()` fetch after the page had already
   mounted. This had existed since before today's changes; nothing to do
   with Strict Mode. Fixed by fetching `getConversation()` server-side, in
   the same pass as `getTrip()`/the `?chat=` param, and handing the result
   to `OpenConversation` as `initialDetail` — a new `seedConversation`
   context method applies it directly with zero client fetch.
7. Also fixed along the way: a **real double-scrollbar bug** (`html`/
   `body` only ever hid horizontal overflow and used `min-height: 100vh`
   on `body`, letting the Trip Hub page's extra Weather/Saved-Places
   column push total height a hair past the viewport and add a second,
   page-level scrollbar next to the message log's own intended one; fixed
   with `height: 100%` + `overflow: hidden` on both) and a **backend gap**
   (`GET /conversations` didn't expose each conversation's `trip_id`, so
   the sidebar couldn't route a chat that already has a generated
   itinerary straight to its real Trip Hub page — it always landed on the
   plain chat view instead, one extra click away from Weather/Saved
   Places).

**A real CI catch, not just local testing**: the first push (PR #29)
failed `frontend-lint-and-build` — ESLint's `react-hooks/set-state-in-effect`
rule flagged the sidebar-open `localStorage` read (a `useState`+`useEffect`
pair) as a hard error, missed locally because a plain `eslint .` run
doesn't exit non-zero the same way CI's `npm run lint` step does. Fixed
using the same pattern already established in `hooks/use-mobile.ts` for
reading another client-only external source (`matchMedia`):
`useSyncExternalStore` instead of `useState`+`useEffect` — no effect
needed at all, and React handles the server/client hydration divergence
internally rather than the manual "start false, flip true after mount"
two-step it replaces.

Verified: clean `tsc --noEmit` and `eslint` (only pre-existing, unrelated
`<img>`/lint items carried over from `ChatApp.tsx`), a successful
production build, a booted standalone production server with no console
errors, and user-confirmed live in their real (authenticated) browser
that chat switching no longer flashes/reloads. Two commits, one PR (#29,
merged via a fast-forward merge, branch deleted after); CI green
(`frontend-lint-and-build`, `lint-and-test`) before merge.

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
