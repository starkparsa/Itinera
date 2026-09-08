# Decisions — Itinera

What was decided, why, and when to revisit. Consolidated 2026-09-02 from
what had been a single sprawling decision-log table in `CLAUDE.md`; the
full blow-by-blow incident narratives behind each entry (exact error
messages, live-verification traces) live in [`progress.md`](progress.md)
instead — this file keeps only the decision, the reason, and the trigger
to revisit.

## Architecture

**Everything routes through one endpoint, `POST /trips/generate`.**
`classify_intent` runs first and sorts every message into `new_trip` /
`edit_trip` / `question` / `off_topic` before anything expensive runs —
this is what stops plain questions from producing nonsensical fake
itineraries, and lets off-topic requests short-circuit for free.
*Revisit: if a genuinely different entry point (e.g. a dedicated
`/questions` endpoint) becomes worth the split — not needed as of this
writing.*

**`generate_trip`'s three reply-path branches split into named helpers,
2026-09-06 (PR #33) — `_handle_off_topic`/`_handle_question`/
`_handle_new_or_edit_trip`, matching the file's own existing
`_`-prefixed-module-level-helper convention.** Structural only — same
routing/dispatch logic above, same behavior in every branch, no new
entry point. Done as its own dedicated pass (planned with two Explore
passes plus direct re-verification of every line-number/shared-variable
claim against the actual file before editing), not folded into the
broader 2026-09-06 codebase-cleanup pass, since this is the single most
load-bearing function in the backend and deserved its own full
before/after test run per branch rather than a bundled risk. *Revisit:
if a fourth reply path is ever added, extract it the same way rather
than growing one of the three existing branches to cover it.*

**Three isolated tool-calling loops, not one shared one**
(`agent_service.py`): currency (`gather_trip_context`, paused),
conversational place-context (`answer_question_with_tools`), and
planning-time place-context (`gather_place_context_for_itinerary`). Kept
separate because they have different caching semantics — currency and
planning-context are cached once per conversation forever
(`Conversation.agent_context`); conversational Q&A must run fresh every
turn since a different place can be asked about each time — and each
loop is given only its own tool schema so flipping one loop's kill switch
never exposes another loop's tool as a side effect. *Revisit: never,
without re-examining the caching-semantics argument specifically — this
was learned the hard way (see progress.md, 2026-08-27).*

**Weather is never a Gemini tool.** `weather_service.py` is called
directly by the routers on every trip. "Does this trip get a forecast"
is never a judgment call the model makes, so it costs zero tokens and
never appears in a tool schema. *Revisit: never — this is a permanent
architectural stance, not a temporary simplification.*

**Never let the LLM do date arithmetic.** `date_resolver.py` resolves
relative date phrases ("next weekend," "in two weeks") with real
`dateutil` code, not model reasoning; `current_date` is injected into
every prompt as a fact. *Revisit: never.*

**Tools return small, flat, pre-aggregated JSON, never raw provider
payloads.** Applies to every integration (currency, Wikipedia, Places).
A cost control once tokens cost real money, not just tidiness.

## LLM provider

**Mistral (local) → Gemini API, done.** Workable free tier, no card.
Model has been swapped twice on real, live-discovered problems, not
speculatively:
- `gemini-2.5-flash` (original target) 404s for new API keys →
  `gemini-3.6-flash`. That model hit a hard **20 requests/day** free-tier
  cap, confirmed via a live 429.
- `gemini-3.6-flash` → **`gemini-3.5-flash-lite`** (current), specifically
  to escape that 20/day wall — confirmed a distinct quota bucket, passed
  every mechanical check live.

*Revisit: whenever a `502`/`RESOURCE_EXHAUSTED` recurs, or before relying
on a specific free-tier RPM/TPM/RPD number — these aren't published
statically anymore, verify per-account in AI Studio.* Google's Gemma 4
open-weight models were evaluated and rejected (real structured-output
and instruction-following bugs found live) — don't re-attempt without
addressing those specifically.

**Groq as an automatic fallback**, only on Gemini's HTTP 429, only in
`llm_service.py`'s direct calls — deliberately not wired into the
tool-calling loops in `agent_service.py`, which already degrade
gracefully to `""` on any failure. Verified live end-to-end 2026-08-31.

## Database

**MySQL → Postgres on Neon, done, 2026-08-29.** pgvector lives in the
same instance for the later cross-trip preference-memory feature. No
idle-pause gotcha (unlike Supabase). Trade-off accepted: no bundled
free Auth, so auth was always going to be a separate build regardless.
`DATABASE_URL` is required with no default — a silent wrong default was
exactly what caused the MySQL/SQLite reconciliation mess that prompted
this migration (see progress.md, 2026-08-29).

## Auth

**Google OAuth, built last, per the original plan — now done.** BFF
pattern: Next.js + Auth.js owns the OAuth flow and mints a short-lived
HS256 JWT (`AUTH_BACKEND_SECRET`, shared with the backend) on every
backend call; FastAPI is a stateless resource server. `User.google_sub`
is the identity key, not email. All four phases shipped: UI parity (no
auth) → real login → per-user ownership checks on every endpoint → Google
Calendar push. Email/password (below) was added later as a second, real
auth method sharing this same session/database/onboarding flow — Google
remains the only OAuth provider. *Revisit: the OAuth consent screen is
still "Testing"
status (7-day refresh token cap) — publish to Production once there's a
real domain to register (see STATUS.md's blockers).*

**Email/password added as a second, real auth method — live, 2026-09-07/08
(PRs #47, #50).** Requested via a fully-detailed three-phase brief (Google
+ Facebook + email/password, sharing one session/database/onboarding
flow). Researched the real architecture first and asked three clarifying
questions rather than building the brief's assumed shape verbatim:

1. **No separate `sessions`/token table.** The brief's schema proposed
   one; declined in favor of reusing Auth.js's own JWT session cookie
   (user's explicit choice) — a second, parallel session system alongside
   Auth.js's would be pure duplication, not a real architectural need.
2. **`provider` JWT claim, not a new token shape.** `mintBackendJwt`/
   `get_current_user` gained a `provider` claim (default `"google"` for
   backward compatibility) so `sub`'s *meaning* is explicit per method:
   Google's OIDC subject for `"google"`, this app's own internal
   `User.id` for `"credentials"` (looked up directly, never
   auto-provisioned — a password account can only be created via
   `/auth/register`).
3. **No automatic cross-provider account linking by email.** A brand-new
   OAuth identity whose email already belongs to a different existing
   account gets a clean 401, not a silent link or a unique-constraint
   crash. This app's email/password signup has no email-verification
   step, so silent linking would let an attacker who pre-registered a
   victim's email gain access to whatever account a later real OAuth
   login attaches to that email — the same reasoning `/auth/register`
   already applies to a duplicate email at signup time.

**Facebook was built, then removed** (PR #48 opened and fully working end
to end — verified via a real browser click-through hitting Facebook's own
OAuth endpoint — then closed unmerged; PR #49 stripped the UI placeholder
too). Decided against pursuing a real Facebook integration; Google and
email/password are this app's two live auth methods. *Revisit: if
Facebook comes back, PR #48's diff (closed, not deleted from GitHub) has
the working implementation to restore from, including the email-collision
guard generalized to a `facebook_id` branch.*

**Closing that PR left the real dev database out of sync** — its
migration (`facebook_id`) had already been applied there, so deleting
the branch left `alembic_version` pointing at a revision that existed
nowhere in the repo, breaking every future `alembic` command against
that database. Caught and fixed after the fact (column dropped, version
stamped back to Phase 1's real head), not by any test (SQLite-backed
tests never touch the real database). *Lesson for next time a PR that
already touched a live database gets closed unmerged: roll the database
back to match, don't just delete the branch — see `progress.md`'s
2026-09-07/08 entry for the full incident.*

**A pre-existing race condition in `profile.py`'s get-or-create, found
during that work, fixed separately — live 2026-09-08 (PR #53).**
`_get_or_create_profile`'s SELECT-then-INSERT had no protection against
two concurrent requests for the same brand-new user both passing the
SELECT before either committed; newly reachable (not newly introduced)
because the credentials login flow's client-side redirect reaches
`GET /profile` faster/more concurrently than Google's full-page OAuth
round-trip ever did. Fix: catch `IntegrityError` on the losing request's
commit, roll back, and re-query for the winning request's row, rather
than adding a lock or changing the read pattern — matches this
codebase's existing preference for the smallest correct fix over a
structural change. *Coordination note: flagged via `spawn_task` to a
peer session rather than fixed inline (out of scope for the auth work in
progress); that session's worktree already held a correct, verified,
uncommitted fix, which was reapplied onto a fresh branch off `main`
directly rather than waited on, to avoid blocking on another session's
own commit timing.*

**Hardening pass (PR #50), from a second brief re-litigating this same
build.** The brief asked to build in-house email/password auth from
scratch; audited the existing code against its own checklist first
(per its explicit "reuse, don't rebuild" instruction) rather than
re-implementing — nearly everything it asked for already existed. Two
real gaps closed: auth-event logging (signup/login success and each
distinct failure reason, never the password) and a small static
common-password blacklist (catches e.g. `Password1!`, which passes every
character-class rule but is a first guess in any real credential-
stuffing attempt). A third candidate — shortening Auth.js's shared
session cookie from its 30-day default toward the brief's 1-24h
guidance — was declined: that setting is shared with Google logins too,
and the actual backend-facing JWT already expires every 60 seconds
regardless of the session cookie's length.

**Calendar: `googleapiclient` directly, not the Calendar MCP server** —
reversed from an earlier plan. `google-genai`'s MCP support was still
"experimental" and the Calendar MCP server itself was gated behind a
non-GA preview program at implementation time. Also the better
architectural fit independent of that: pushing to a calendar is a
deterministic user click, never a Gemini judgment call.

## Database access control (RLS) — live, 2026-09-08

**Originally investigated 2026-09-06, not built.** User asked to enable
Postgres row-level security on every table, with real per-user policies
(no `USING (true)`). Investigated before writing any SQL: this app isn't
Supabase-shaped — there's exactly one Postgres role for the whole
backend (`DATABASE_URL`, one connection string, no per-request Postgres
identity of any kind), and authorization was enforced entirely in the
API layer (`user_id == user.id` filters in every router, verified real —
not cosmetic — in `docs/security-review.md`).

Two blockers were identified at the time: the table owner bypassing RLS
by default (needing `FORCE ROW LEVEL SECURITY`), and a chicken-and-egg
problem on `users` (`auth.get_current_user` looks a row up *by
`google_sub`*, before the app knows that user's internal id — the id a
naive `user_id`-keyed policy would need already in a session variable).
Presented to the user rather than faking policies that would do nothing;
paused without a decision at the time.

**Picked back up 2026-09-08 — and the first blocker turned out to be
worse than described.** Built the session-identity plumbing exactly as
scoped (a SQLAlchemy `after_begin` hook setting
`set_config('app.current_user_id', ..., true)` at the start of every
transaction, populated by `auth.get_current_user` on `session.info`),
wrote the Alembic migration (`ENABLE`/`FORCE ROW LEVEL SECURITY` plus a
`user_id`-keyed policy on 6 directly-owned tables, and an `EXISTS`-subquery
policy for the 3 FK-hop tables — `messages`→`conversations`,
`itinerary_items`/`saved_places`→`trips`), applied it to the real dev
database, and verified with a real two-temporary-user isolation script
(cross-user read blocked, cross-user write rejected, no-identity-set
sees nothing) — and it did **nothing**. Every row was visible regardless
of identity.

Root cause: `FORCE ROW LEVEL SECURITY` only overrides *ownership*-based
bypass. Neon's default project-owner role (`neondb_owner`, the one and
only role this app had) carries the `BYPASSRLS` attribute directly —
unconditional, applies regardless of `FORCE`, and unrelated to table
ownership. This is a strictly harder blocker than the 2026-09-06
write-up anticipated (that entry assumed ownership was the only issue).

**Resolution: a second, non-bypass Postgres role (Option 2 of three
presented — see this session's transcript for the other two: revoking
`BYPASSRLS` from `neondb_owner` directly, or shelving RLS again).**
Created `itinera_app` — `LOGIN`, no `BYPASSRLS`, no `SUPERUSER` —
granted `SELECT`/`INSERT`/`UPDATE`/`DELETE` on all tables plus
`USAGE`/`SELECT` on all sequences, and (to avoid an ongoing
per-migration maintenance burden) `ALTER DEFAULT PRIVILEGES FOR ROLE
neondb_owner` so any table a *future* Alembic migration creates is
automatically usable by `itinera_app` with no extra grant statement.
`neondb_owner`/`DATABASE_URL` stays exactly as before — schema owner,
what Alembic migrates against, untouched. The app's own queries now run
as `itinera_app` via a new `APP_DATABASE_URL` env var (`database.py`
falls back to `DATABASE_URL` when unset, so sqlite dev/tests and any
environment that hasn't provisioned the second role keep working
exactly as before — unenforced, not broken). Re-ran the same isolation
script against `itinera_app`: every check passed, including the FK-hop
case (`itinerary_items` via `trips`).

**`users` is deliberately excluded from RLS**, a scope decision made
during this build, not carried over from the original plan. `/auth/register`
and `/auth/login` (routers/auth.py) both look a row up *by email* with no
established identity at all — that's structurally what "login" means —
which no per-user policy can accommodate without a *third*,
bypass-capable role scoped to just those two endpoints (real added
infra, not justified for what's already covered: email/`google_sub`
unique constraints, bcrypt hashing, and `get_current_user`'s exact-match
lookups protect that table today, unchanged by this work).

**Operational note for future direct DB access** (psql, an admin script,
a migration's data backfill): a plain `itinera_app` connection sees NO
rows in any RLS-governed table unless it first runs
`SELECT set_config('app.current_user_id', '<id>', false);` in that
session — intended fail-closed behavior, not a bug, but easy to mistake
for "the data's gone" the first time it's hit. Scripts needing
unrestricted access (like the orphaned-migration cleanup in the Auth
entry above) should keep using `DATABASE_URL`/`neondb_owner`, same as
before.

*Revisit: none currently planned — this closes the gap identified
2026-09-06. If a 10th table is ever added, remember it needs its own
policy in a migration (direct `user_id` or FK-hop, matching whichever
shape applies) — `ALTER DEFAULT PRIVILEGES` only covers the *grant*, not
the RLS policy itself.*

## Place context: Wikipedia + Google Places

**Wikipedia-only tool shipped first** (2026-08-27), scoped down from a
fully-researched Google Maps integration that needed a billing account
with no genuinely free tier. **Extended with Google Places**
(`get_place_details`, `find_nearby_places`) on 2026-09-01 once a real,
user-supplied, billing-enabled API key existed. The two sources
deliberately don't overlap: Wikipedia stays free and covers
history/cultural-significance; Places (billed, used more sparingly per
explicit prompt guidance) covers current/practical facts (rating, hours,
price) and real nearby recommendations — something Wikipedia has no
equivalent of. `GOOGLE_PLACES_API_KEY`'s presence is itself the kill
switch, same convention as `GROQ_API_KEY`. *Revisit: if Places billing
becomes a real cost concern, or when Maps/routing (below) gets built —
confirm the two features stay non-overlapping.*

## Maps/routing — not built

Reversed twice: OSM-based stack (Nominatim/Overpass/OpenRouteService) →
Google's official Maps MCP server (once Google shipped one, bundling
weather-forecast grounding) — **unverified as of the decision**, Google's
announcement didn't disclose pricing/free-tier/auth flow. *Revisit:
confirm those three facts live before writing any code against it —
don't assume the old OSM-based design transfers.*

## Weather — resolved

Real-time, per-day, via Open-Meteo — **not** an MCP server, **not** a
Gemini tool at all (see Architecture section above). OpenWeather was
tried first and removed after proving unreliable in practice (root cause
never fully diagnosed). *Revisit: only if Open-Meteo itself starts
failing — don't reach back for OpenWeather without a new reason.*

## Currency conversion — paused, not removed

`gather_trip_context()`/`convert_currency` (Frankfurter, free) is the
currency tool-calling loop — the only tool it ever calls. Re-enabled and
verified working correctly (2026-08-25: a real Frankfurter call was
correctly folded into a grounded summary), then **paused again the next
day purely as a product decision that currency conversion isn't a needed
feature** — not a reliability finding, unlike weather above. The kill
switch (`AGENT_TOOL_CALLING_ENABLED = False`) stays specifically so this
can flip back on without rebuilding anything. *Revisit: if the product
decision changes — the code and tests are fully intact behind the flag,
this is not a pruning candidate.*

## Event discovery: Ticketmaster — live, 2026-09-04

**find_events (Ticketmaster Discovery API, free tier confirmed live:
5,000 req/day, no card) added as a fourth tool**, alongside the three
place tools, reached through the same two on-demand loops
(`answer_question_with_tools`/`gather_place_context_for_itinerary`) —
not a separate always-on step, and not a new persistent interest
profile. All three scope calls confirmed with the user before building:
interests read fresh from the prompt each turn (doesn't pull the
deliberately-last cross-trip-memory/pgvector item forward); discovery is
on-demand only; an event can set a trip's `start_date`, but only on
explicit commit phrasing.

**A committed-to event's real date can set `start_date` — 2 days before
the event, for settle-in time (`event_planning.py`,
`SETTLE_IN_DAYS = 2`, a single tunable constant) — but only when the
request's own wording truly commits ("build a trip around X"), never for
a plain browsing/interest question.** Detected via a structured,
deterministic marker (`PLANNING_TOOL_SYSTEM_PROMPT` instructs the model
to emit `COMMITTED_EVENT_ID: <id>` on its own line only on genuine
commitment, `event_planning.extract_committed_event_id` regex-matches
that exact line — never fuzzy prose parsing) rather than trusting a
find_events call's mere existence, or the model's own judgment call, as
the signal — a narrow search returning one result is not the same thing
as the user having committed to it. The resolved event is always
re-fetched by id (`ticketmaster_client.get_event`) before its date is
trusted, never taken from a possibly-stale earlier tool result. Tried as
a fallback, same tier as `previous_trip.start_date`, only when the
prompt's own text didn't already resolve an explicit date — an explicit
date always wins, unchanged.

**No new `TripRequest` field, no frontend/UI change** — the whole flow
reuses this same day's Saved Places plumbing exactly: `_run_tool_loop`'s
raw tool-call results already flow up through `generate_itinerary`'s
`result["found_places"]`, so `find_events` cost nothing extra to wire
into that existing channel. *Revisit note updated 2026-09-07: a Trip Hub
card was built and merged (PR #40) — see this file's "Four follow-on
features" entry below for the approach (live per-trip fetch, 6h TTL, no
new table).*

**Ticketmaster's `keyword` param does literal name-matching, not genre
matching — confirmed live, not assumed.** Searching `keyword="jazz"`
returned "Miami Heat vs. Utah Jazz" (matched on the opposing team's
name, not an actual jazz show). Switched to `classificationName`
instead, confirmed live to return real genre-correct results for both a
music genre and a sport. *Revisit: never switch back to `keyword` for
interest matching without re-reading why.*

## Flights — not built

No workable free flight-pricing API exists (Amadeus self-service was
decommissioned). Scoped into three genuinely different pieces when
discussed 2026-09-02: **booking** (deep-link to Google Flights/Kayak, no
new dependency, buildable today), **price tracking** (blocked on
verifying a real free data source — Travelpayouts/Aviasales is the
current unverified candidate — plus this app has no background-job
runner at all yet, which price tracking would be the first feature to
need), **prediction** (real ML modeling needs months of accumulated price
history this app doesn't have yet; a cheap, honest version — "this fare
is X% above its own 30-day average" — is derivable from the same
tracking data with zero ML). *Revisit: live-verify Travelpayouts/Aviasales
before writing a client for it — that's the actual next step, not a
design question.*

## Hotels — not built

Search/compare only, deep-link out — real reservations need PCI-compliant
payment flows and hotel partner agreements, out of scope.

## Cross-trip preference memory — not built, deliberately last

Materially different from within-conversation memory (already have that,
via `Conversation.agent_context` and chat history). Needs pgvector (see
Database entry) and real design work; don't pull forward without a
specific reason.

## Onboarding personalization & account details — live, 2026-09-06

**`UserProfile`, 1:1 with `User`, mirrors `GoogleCalendarCredential`'s
shape** (unique FK, no separate index — the unique constraint already is
one). Every field nullable; the onboarding form is fully skippable, so a
partially-filled profile is the normal case, not an edge case.
`interests`/`bucket_list_countries` are JSON-encoded `Text`, matching
`Trip.weather_json`'s existing small-blob convention rather than a child
table for values nothing filters on individually. Two migrations, both
purely additive — no existing table touched.

**Personalization reaches the prompt through the same append pattern
`answer_question`'s `agent_context` already uses**, not a new mechanism:
`_build_user_profile_note` (`routers/trips.py`) builds a short string from
only the fields actually set, threaded into `generate_itinerary`/
`_generate_chunk`'s existing `context_parts`, with the same "use to
influence choices, don't invent facts" caution already applied there.
`llm_service.py` stays free of any DB import — the note is built in
`routers/trips.py` and passed in as a plain string, preserving a boundary
that already existed before this feature.

**Account-details fields (name, mobile, date of birth, country) are each
tied to a real, committed use, not collected speculatively** — this was
a real correction mid-build: the fields were first scoped out entirely
(no consuming feature existed), then reintroduced once genuine features
were committed to. `date_of_birth` feeds a real, live feature: coarse
age-bracket personalization (`_age_bracket`, real date arithmetic against
today's actual date — CLAUDE.md principle #6 — never an LLM guess).
`mobile_number` does not yet have its sending feature built — see the SMS
entry below. `display_name` isn't a `UserProfile` column at all; it's
`User.display_name`, written through the same single `PUT /profile` call
so the "what should we call you" question doesn't need a second endpoint
(a blank submission never clears the real name — only a non-empty value
overwrites it).

**Validation lives in the Pydantic schema, not a separate layer** — a
phone-shape regex and a date-of-birth bounds check (`not future`, `not
over 120 years`) on `ProfileUpdate`, mirrored client-side in
`OnboardingFlow.tsx` as a courtesy (catch it before a round trip); the
backend validator is what's actually authoritative. No mirrored
client-side schema beyond that — Pydantic's own 422 was judged sufficient
for a 3-input form with no exotic types.

**Toast notifications: hand-built, not a library** (`components/ui/toast.tsx`)
— a `ToastProvider`/`useToast` context mounted once at the app root, real
`role="status"`/`aria-live="polite"` announcement, auto-dismiss.
Itinera's first-ever ambient-notification primitive; every future
celebration/confirmation moment (a badge earned, an export succeeding)
routes through this one component instead of each feature inventing its
own. First real consumer: onboarding's save confirmation.

**`/profile` page, and `OnboardingFlow` reused for editing** — the
original design called for the same onboarding component to serve both
the first-login gate and a later "Profile → Edit preferences" page; the
first build shipped only the gate, leaving `/profile` referenced in a
docstring but not actually reachable from anywhere. Closed by adding a
`mode: "onboarding" | "edit"` prop (edit mode: "Cancel" instead of "Skip
for now", never calls the skip endpoint) and a real `/profile` route,
linked from the sidebar.

**Frontend test framework introduced for the first time**: Vitest +
React Testing Library (`vitest.config.mts`, `vitest.setup.ts`), chosen
over Jest for faster startup and native Vite/TS handling with no separate
transform config. Nothing in this frontend had an automated test before
this — `OnboardingFlow`'s form/validation/step logic and the new toast
component are the first two files with real coverage (12 tests).

**Real bug found and fixed: native `<select>` popups unreadable in dark
mode.** Every select in the onboarding form inherited the app's
dark-mode text color while its native OS dropdown popup still rendered
on a light background — unselected options went light-on-white, nearly
invisible (caught from a user screenshot, not a code review). Fixed with
one shared utility, `[color-scheme:light]` on the field class every
select already used — verified as a real compiled CSS rule in the
production bundle, not just present in source, plus a regression test.

**SMS trip-day reminders — explicitly not built.** `mobile_number` exists
because a real feature (SMS reminders) was committed to, but the sending
pipeline itself needs an external provider, a real `$0`-tier check (per
CLAUDE.md's budget constraint), a scheduling mechanism this app has no
equivalent of yet, and opt-in UX — genuinely separate, larger scope, not
something to bundle into a form field. *Revisit: when a specific SMS
provider's free tier has been live-verified, the same way Travelpayouts/
Aviasales still needs to be for flight tracking.*

**Manual end-to-end verification stops at the real OAuth handshake.**
Both dev servers were started for real, live-verified: the backend's own
Swagger UI lists all three `/profile` endpoints, `/`, `/trips`, and
`/profile` all correctly redirect an unauthenticated request to `/login`,
and a real unauthenticated `GET /profile` returns a genuine 401.
Completing sign-in itself needs the user's real Google credentials, which
isn't something to automate. *Revisit: a real signed-in click-through
(sign in, complete/skip onboarding, reload, confirm gating) is still
outstanding and is the most valuable next verification step.*

## Four follow-on features built, 2026-09-07 — PRs #39–42, merged

Four gaps flagged after onboarding personalization shipped (this file's
entry above) were scoped into one plan and built as four isolated
branches/PRs, in this order, all now merged to `main` (after PR #43,
below, fixed a broken `main` CI first).

**1. Onboarding chip/tag visual polish (PR #39).** Replaced five
`<select>`s and the interests checkbox group with a new interactive chip
control (`components/ui/toggle-chip.tsx`) — a real, visually-hidden
`<input type="checkbox"|"radio">` styled via a sibling `<span>` through
Tailwind `peer-*` selectors, not a `<div onClick>` reimplementation, so
keyboard/screen-reader behavior is native. `country_region` deliberately
stays a plain `<select>` — 5 options plus a conditional "Other" text
branch is what a select already does cleanly; chip-ifying it would add a
6th chip that then reveals a text input, which reads as more awkward.
No new state shape — chips plug into `OnboardingFlow`'s existing
`set<K>`/`toggleInterest` setters unchanged.

**2. Events Trip Hub card (PR #40).** `find_events` had worked
conversationally since 2026-09-04 (this file's Event discovery entry
above) but had no UI surface — this closes that gap, updating that
entry's own "Revisit" note. **Chosen approach: live per-trip fetch
cached on the `Trip` row with a 6h TTL, mirroring `weather_service.py`
exactly** (`Trip.events_json`/`events_fetched_at`, new
`events_service.py`) — not a new `SavedEvent` table. Reasoning: a
`SavedPlace`-style table exists because places accumulate across a chat
loop and need per-tool-call dedup; an Events card is one read per
trip-page load, not something accumulated the same way. Not routed
through the Gemini tool-calling loop, same "never a model judgment call"
reasoning as weather. *Revisit: never, without re-examining the
per-trip-fetch-vs-persisted-table tradeoff specifically.*

**3. Auth-testing gap — closed with documentation, not new test
infrastructure (PR #41).** "No real signed-in click-through has
happened" (this file's entry above, and `STATUS.md`) turned out to be
two different claims, only one of which was a real gap:
`backend/tests/conftest.py`'s `override_auth()` fixture already fully
mocks `get_current_user` for the automated suite — nothing to build
there. The actual remaining gap, a genuine browser OAuth click-through,
can't be meaningfully automated: this app's BFF architecture means
FastAPI never talks to Google at all (only verifies a JWT Auth.js
mints), and no E2E framework exists in this repo. Standing up Playwright
plus an OAuth-mocking approach to test Google's own consent screen would
be disproportionate for what it proves. **Decision: a human-run runbook**
(`docs/manual-auth-testing.md`) is the deliverable, explicitly not a
pytest fixture or an E2E suite — so this doesn't get re-litigated as a
gap later. One legitimate small gap-filler landed alongside it: a real
unit test on `mintBackendJwt.ts` (the actual signer, not a Google mock).
*Revisit: only if this app ever adds a browser E2E framework for other
reasons — then, and only then, is automating this specific flow worth
reconsidering.*

**4. Gamification: passport stamps + tiered badges (PR #42).** Builds
the mechanic already confirmed in `docs/design-references.md` and
declines the two ideas this file's Gamification-deferred entry below
scoped out (shareable card, seasonal badges — still deferred, unchanged).
Deliberately jumps ahead of Maps/routing in `STATUS.md`'s existing build
order — a discussed, not silent, reordering.

- **XP is derived, never incremented.** `UserStats.xp_points` is *set*
  to `real_trip_count * 10` on every `GET /gamification/passport` call
  (not incremented at a trip-generation hook), and achievement rows are
  only inserted for codes that don't already have one — the whole
  evaluation (`gamification_service.evaluate_and_award`) is idempotent
  and safe to call on every request, with no double-award or
  missed-award risk from calling it more than once. Simpler than the
  originally-sketched "hook into trip generation" design (an earlier,
  unbuilt plan draft) once it became clear a single read-time evaluation
  point removes an entire class of double-counting bug for free.
- **A real correctness bug found during implementation, not merely
  planned around: `_handle_new_or_edit_trip` inserts a fresh `Trip` row
  on *every* `new_trip` and `edit_trip` turn**, not just new trips (its
  own docstring already said this, but nothing downstream depended on
  the distinction until now). Without accounting for that, a
  conversational "make it more relaxed" would inflate trip counts,
  badges, and passport stamps every time someone tweaks an
  already-planned trip. Fixed with a new `Trip.is_edit` column, set from
  the already-classified intent at creation time; `stats_service.py`
  filters on it everywhere. *Revisit: if `edit_trip` ever becomes a true
  in-place edit instead of a new row (see this file's Architecture
  section, `_handle_new_or_edit_trip`'s own docstring) this flag becomes
  unnecessary — don't remove it without confirming that's actually
  landed.*
- **Countries-visited heuristic is a small, static, explicitly
  non-exhaustive substring lookup** (`stats_service.CITY_OR_KEYWORD_TO_COUNTRY`,
  ~40 entries) — never a geocoding API call (budget), never a guess for
  an unrecognized destination (principle #7). Silently undercounts;
  never overcounts. No disambiguation for ambiguous names (e.g.
  "Georgia" the state vs. the country) — documented as a known
  limitation in the module itself rather than solved.
- **A real theming bug found and fixed while building this, not just
  for this component**: Tailwind `dark:` utility classes silently never
  apply anywhere in this app. This app's dark mode is OS-preference-driven
  via `@media (prefers-color-scheme: dark)` (see the UI styling section
  below), not a `.dark`-class toggle, which is what Tailwind's `dark:`
  variant actually targets here (`@custom-variant dark (&:is(.dark *))`)
  — so every `dark:`-prefixed class in this codebase (some pre-existed
  in shadcn-generated files) has always been dead code. Fixed properly
  for the new passport-stamp accents: 8 named `--stamp-*` CSS custom
  properties (light values in `:root`, dark overrides in the existing
  `prefers-color-scheme` block, registered in `@theme inline`), following
  the exact pattern already established by `--chat-assistant-*` — not
  `dark:` classes, which would have looked correct in a light-mode
  screenshot and been silently broken for every real dark-mode user.
  *Revisit: the pre-existing `dark:` classes elsewhere (`TripCard.tsx`,
  `TripView.tsx`, and shadcn's own `badge.tsx`/`button.tsx`/`textarea.tsx`)
  are the same dead pattern — not touched in this PR (out of scope), but
  worth a dedicated cleanup pass if anyone is ever debugging why a
  dark-mode style "isn't working."*

**5. CI on `main` was found broken, separately, while opening these PRs
(PR #43, not part of the four-feature plan).** Every one of the four PRs
above failed CI in under 20 seconds — too fast to be a real test
failure. Root cause: `main` itself had been red since PR #38 merged
(`gh run list --branch main` confirmed it), two unrelated pre-existing
issues neither caught before that merge — `npm ci`'s `ERESOLVE` (
`vitest@5.0.0` peer-requires `@types/node@"^22.0.0 || >=24.0.0"`, but
`package.json` had it pinned to `^20`, apparently never hit locally
under `--legacy-peer-deps`) and an unsorted-import `ruff` failure in
`tests/test_trips_router.py`. Both are pure fixes (a version bump plus
`ruff --fix`), no behavior change. *Revisit: `npm ci`'s strict peer
resolution caught something `npm install --legacy-peer-deps` didn't —
worth checking new frontend dependencies with a real `npm ci` locally
before merging, not just the more forgiving install flow used
day-to-day.*

## Login page redesign — live, 2026-09-07 (PR #45)

**Corrected the premise before building anything, twice.** Both the
initial "add a Sign Up CTA" request and the later full redesign brief
assumed a traditional email/password login-vs-signup split (password
fields, "Forgot Password?", wrong-password error states, a separate
signup flow to link to). This app has none of that — Google OAuth is
the only auth method (see this file's Auth entry), and one button
already handles both new and returning users identically
(`backend/app/auth.py`'s `get_current_user` auto-provisions a `User`
row the first time it sees a new `google_sub`). Confirmed direction
with the user before designing or coding either time, rather than
silently building a fictional second auth flow or quietly reversing
the "Google OAuth only" decision.

**What actually shipped, in three passes on one PR:**
1. A copy-only fix: one reassuring line under the button ("New here?
   Signing in with Google creates your account automatically").
2. A full visual redesign — approved first as a mockup artifact
   (Login/Signup chip-tab toggle, Google/Facebook/email options,
   error/loading states, a spec sheet), then integrated for real.
   Facebook and email/password are drawn to full visual parity but
   **honestly toast "isn't available yet" on every interaction**
   (click, submit, forgot-password) rather than faking a successful
   sign-in or fabricating a "wrong password" error — nothing here
   pretends to work. Google remains the one real, wired method.
3. A "Dusk City" background, added per follow-up feedback: a gradient
   + inline SVG skyline built from this app's own two named hues
   (indigo 265°, copper 55°) — no photo asset, so nothing to license
   or host. Deliberately **not** theme-reactive, unlike every other
   token in this app — a fixed brand moment for this one screen,
   the same way a hero image would be, while the card floating on it
   still fully respects real light/dark tokens. *Revisit: never,
   without re-examining the fixed-vs-reactive-background tradeoff
   specifically.*

**Declined a follow-up request to replace that background with live
Pexels photos.** Technically buildable (`pexels_service.py` already
proves the pattern for trip photos) but would have meant a new
*public*, unauthenticated backend endpoint — `/login` is the one page
in this app with no session yet — plus a real third-party dependency
and rate-limit exposure on the single most reliability-critical page
in the app. Confirmed with the user to keep the zero-dependency Dusk
City background instead. *Revisit: only if a specific, scoped version
of this (not the full original Phase 1–3 brief) is explicitly
requested again — the architectural objection (new public endpoint)
would need addressing either way.*

**Two real bugs found during integration, not just planned around:**
- This app's `globals.css` sets `overflow: hidden` on `html`/`body`
  (intentional, so `ChatApp`'s own inner region is the only thing that
  scrolls) — unpatched, that rule would have trapped `/login`'s content
  with no way to reach it once the card (email form open, gamification
  hint, switcher line) grew taller than a short viewport. Fixed by
  giving the login page its own `h-screen`/`overflow-y-auto` region,
  the same one-scroll-region-per-page contract, just scoped to this
  page instead of `ChatApp`'s.
- The email "submit" button relied on native `<form onSubmit>`, but
  this app's `Button` wraps a `@base-ui/react` primitive that doesn't
  reliably forward `type="submit"` through to a real submit control —
  caught by two failing tests, not by eyeballing. Fixed by switching to
  the `onClick`-only convention `OnboardingFlow.tsx` already
  established (every save/continue action there is wired via `onClick`
  on a `Button`, never native form submission). *Revisit: don't rely on
  native `<form onSubmit>` + a submit-type `Button` anywhere else in
  this app without verifying it actually fires first.*

## UI styling

**Tailwind CSS v4 + shadcn/ui**, replacing ~350 lines of hand-written CSS
(2026-08-29). Teal ("ocean/exploration") accent replaces both the old
bespoke Streamlit-leftover red and shadcn's default grayscale — Tailwind's
own teal-700/teal-400 oklch stops, not hand-picked. Dark mode stays
`prefers-color-scheme`-driven, no toggle, no JS theming dependency.

**Palette: Direction C, "Dusk City," chosen 2026-09-03, wired into
`globals.css` 2026-09-04** — indigo primary (`oklch(0.45 0.11 265)`) +
copper tour-guide accent (`oklch(0.58 0.15 55)`), replacing the teal/amber
pair above. Picked from four researched directions in
`docs/design-references.md`'s Palette Directions artifact for a
travel-evocative feel without going literally nature- or
city-photograph-themed. Every token (including neutrals, hue-locked to the
same 265° rather than plain grey) is now live, not mockup-only. *Revisit:
the base indigo values were verified against WCAG AA 2026-09-04 (see the
contrast-check entry below) — the copper accent's light-mode lightness
changed as a result; nothing else here should need revisiting on that
front again.*

**A real WCAG AA contrast check on Dusk City, 2026-09-04 — found and
fixed two failures, both in light-mode tour-guide mode.** Computed actual
oklch->sRGB contrast ratios (a small script, not eyeballing hex values)
for every text/background and UI-component pair across the palette,
light+dark × normal+tour-guide (~20 pairs). White button text on the
original copper `--primary` (`oklch(0.58 0.15 55)`) only reached 4.31:1
against the 4.5:1 minimum; the tour-guide badge (`text-primary` on
`bg-secondary`) similarly landed at 4.13:1. Checked both directions
before picking a fix — even the app's own dark `--foreground` text
topped out at 4.40:1 against that same copper, so the accent itself was
too mid-toned in *either* text-color direction, not just the wrong
choice of white vs. dark text. Fixed by darkening the light-mode
tour-guide `--primary`/`--ring`/`--sidebar-primary`/`--sidebar-ring` to
`oklch(0.45 0.15 55)` — matching the base indigo's own light-mode
lightness exactly, so both accents now read as "equally dark" as a
system. Now 7.47:1 / 7.15:1. Every other pair checked (dark mode
entirely, the `--chat-assistant-*` trio, the destructive/emerald/sky
Alert variants) already passed with real margin. *Revisit: any new color
token added to `globals.css` should get the same computed check before
shipping — a plausible-looking oklch triple is not evidence of AA
compliance, as this entry demonstrates.*

**The assistant's chat bubble never recolored in tour-guide mode — only
the user's own did, since only the user bubble ever rode `--primary`
directly.** Fixed 2026-09-04 alongside the palette wiring: three new
tokens (`--chat-assistant-bg`/`-border`/`-fg`, defaulting to the existing
card tokens so normal mode is pixel-unchanged) get overridden to a soft
copper tint inside the same `[data-tour-guide-mode="true"]` block that
already swaps `--primary`. No new JS state — `ChatMessage.tsx` just reads
different tokens, the existing attribute-selector mechanism does the rest.

**UI direction: "Trip Hub v2," chosen 2026-09-03, after a same-day
rejected exploration.** A "City Passport" direction — the interface framed
as a boarding-pass/travel document, with ink-stamp result cards and a
literal app "Passport" tab of past trips — was fully built (two artifacts,
kept in `docs/design-references.md` as a recorded dead end) and then
explicitly rejected by the user once seen in full. The direction that
replaced it rebuilds the original UX Directions canvas's "Trip Hub"
concept (a persistent trip-list + active-trip view, not chat-only) as
standard product UI in the Dusk City palette — flat buttons, real
city-photo thumbnails, no travel-document metaphor. *Revisit the rejection
only if the user brings the travel-document idea back up themselves —
don't re-propose a stamp/passport metaphor by default.*

**Both the trip sidebar and the Trip Hub's data-cards column are
collapsed by default, opened only on request** — the strongest form yet of
the "don't show a tool before it's been asked for" principle, extended
from individual data cards (below) to the surrounding chrome itself.
In the mockup this was `display: none` (not `width: 0`, which silently
broke the responsive stacked layout); the real implementation
(`ChatApp.tsx`/`TripHubPanel.tsx`, 2026-09-04) uses React conditional
rendering, the framework-native equivalent. *Revisit: if this needs to
become a persisted-per-user preference rather than always-collapsed-by-
default, that's real state (localStorage or `User` row), not component
state.*

**Trip Hub v2 wired into the real app 2026-09-04**: `GET /trips` (new
endpoint) + `/trips` and `/trips/[tripId]` (new frontend routes). Reuses
`ChatApp`'s existing message rendering for the Trip Hub page (via new
`initialConversationId`/`rightPanel` props) rather than building a second
chat renderer; the day-by-day itinerary is deliberately not duplicated
outside the chat stream either, for the same reason — it already renders
via `TripView` inside the message that generated it.

**`GET /trips` shows one card per conversation, not one per `Trip` row —
a real bug found and fixed the same day it shipped.** `generate_trip`
creates a brand-new `Trip` row on every `new_trip`/`edit_trip` turn (it
never updates one in place — see `edit_trip`'s own note above); the first
version of `list_trips` listed every row unfiltered, so a conversation
refined 4 times showed up as 4 duplicate cards — confirmed against a real
user's live data. Fixed by keeping only the latest `Trip` per
`conversation_id`. The first fix attempt (`GROUP BY
coalesce(conversation_id, id)`, to give conversation-less orphan trips
their own group) had its own real bug, also caught before shipping: `Trip`
and `Conversation` ids are independent sequences that can produce the same
number, so an orphan's own id could numerically collide with an unrelated
trip's real `conversation_id` and wrongly merge the two. Replaced with two
separate, unioned queries (grouped-by-conversation trips; conversation-less
trips standing alone) — structurally collision-proof rather than just
unlikely to collide. *Revisit: never revert to the single coalesced-key
form without re-reading why.*

**Chat UI moved into a shared Next.js layout, 2026-09-05 (PR #29) —
`ChatApp.tsx` (546 lines: sidebar, message log, composer, all state) split
into `ChatShell.tsx` (the persistent shell) + a tiny `OpenConversation.tsx`
bridge, via a new `app/(chat)/layout.tsx` route group wrapping both `/`
and `/trips/[tripId]`.** Root cause this fixes: those two routes were
previously direct children of the bare root layout with nothing shared
between them, so every switch between them fully remounted the entire
chat UI (sidebar included) and separately re-ran `auth()` + fully
uncached backend fetches (each re-minting a JWT) — read by users as "the
whole chat refreshing every time," and confirmed via a real DevTools
Network-tab capture, not assumed. Next.js's App Router does not remount a
shared layout on navigation between sibling routes under it, only the
page segment that actually changed, which is the mechanism this relies
on. `ChatShellContext` exposes `openConversation`/`seedConversation` so
each page can tell the persistent shell which conversation to show
without owning any chat-rendering logic itself. *Revisit: if `/trips`
(the "Your Trips" list, deliberately left outside this route group since
it doesn't use the chat UI at all) ever needs to share chrome with the
other two, re-evaluate the group boundary then — don't assume it should
just be folded in.*

**Conversation detail fetched server-side, alongside trip data, instead
of by the client after mount — 2026-09-05, same PR.** Confirmed via a
second Network-tab capture (against a genuine production build, which
rules out React Strict Mode's dev-only double-invoke as an explanation)
that every chat switch did two separate slow round trips in sequence:
`getTrip()` server-side, then a *second*, separate client-initiated
`getConversation()` fetch only after the page had already mounted. Since
`backend.ts`'s functions are Server Actions (`"use server"`), calling one
directly from another Server Component (a page) runs it in the same
request with no extra browser round trip — only calling it from a
*client* component crosses the network. Fixed by having
`trips/[tripId]/page.tsx` (and `(chat)/page.tsx` for the `?chat=` case)
fetch `getConversation()` themselves and pass the result to
`OpenConversation` as `initialDetail`, which a new `seedConversation`
shell method applies with zero client fetch. *Revisit: any new page that
needs to open a specific conversation on load should follow this same
"fetch server-side, seed directly" shape — falling back to
`OpenConversation`'s client-fetch path (`openConversation(id)` with no
`initialDetail`) reintroduces the exact double-round-trip this fixed.*

**`ChatShell.tsx` split into three hooks, 2026-09-06 (PR #33) —
`hooks/use-sidebar-open.ts`, `hooks/use-scroll-restore.ts`,
`hooks/use-conversation-loader.ts`.** Was 578 lines (~6 separable
concerns) after the 2026-09-05 chat-switch-bug fix packed several
deliberate, hard-won fixes into one file. Deferred from the 2026-09-06
codebase-cleanup pass to its own dedicated session specifically because
of that fragility — any restructuring risked reintroducing the exact bug
class it had just fixed. Conversation loading/caching and the pending/
error state machine were kept in ONE hook (`use-conversation-loader.ts`)
rather than split further, since `loadConversation` writes `pending`/
`error` directly — a clean per-concern split would've meant passing
setters bidirectionally between two hooks for no real benefit. Every
load-bearing behavior from the 2026-09-05 fix (the Strict-Mode
generation-counter guard, module-scope caches staying module-scope,
`useSyncExternalStore`, `useLayoutEffect` timing, the
`skipCache`+`showLoading` two-flag shape) moved verbatim. `ChatShell.tsx`
is 349 lines now, and `ChatShellContext`'s public contract didn't change
at all — no consumer needed edits. *Revisit: if any of these three hooks
grows its own multiple concerns again, split further then — don't
pre-split beyond what's actually coupled today.*

**`GOOGLE_PLACES_API_KEY`/`PEXELS_API_KEY`/`TICKETMASTER_API_KEY` weren't
forwarded into either Docker Compose file — found and fixed 2026-09-06.**
Same class of gap `docker-compose.yml`'s own comments already recorded
once for `GROQ_API_KEY`: a key set in `.env` silently never reached the
backend container's environment, so `docker compose up` quietly ran with
Places/Pexels/Ticketmaster disabled even with all three keys configured.
Recurred because these three integrations shipped after that earlier fix
and nobody re-checked the compose files against the growing `.env.example`
list. *Revisit: whenever a new optional integration adds an env var,
check both compose files' `environment:` blocks in the same PR — this is
the second time this exact class of gap has shipped.*

**`skills-lock.json` was tracked in git despite its own `.gitignore`
entry saying it shouldn't be — found and fixed 2026-09-06.** Committed
before the ignore rule existed; `.gitignore` doesn't retroactively
untrack a file already in version control. Fixed with
`git rm --cached skills-lock.json` — stays on disk, just no longer
version-controlled.

**A way to actually share a running instance without the full dev setup,
2026-09-05/06 (PR #31) — `docker-compose.share.yml` + `.env.share.example`,
pulling the images CI already publishes to GHCR instead of building from
source.** Confirmed live (not assumed) that
`ghcr.io/starkparsa/itinera-{backend,frontend}:latest` are both publicly
pullable with no login, via a raw anonymous-token manifest fetch against
the registry. Defaults `DATABASE_URL` to a local SQLite file so a friend
needs nothing but Docker and one free Gemini key — no Neon account, no
repo build step. This is deliberately a separate, lighter-weight thing
from the real Cloud Run deployment tracked in
`docs/deployment-readiness.md`, which is still not executed. *Revisit:
if this compose file drifts from the main one's env vars again (as the
Places/Pexels/Ticketmaster gap above did once already), fix both files
in the same PR, not just the one someone happened to be testing.*

**Never run `npx shadcn add <component>` directly in this repo — hand-port
instead, 2026-09-04.** The installed CLI (against this project's
`base-nova` custom style, Base UI not Radix) wants to overwrite
`button.tsx` unprompted and adds a stray `cn` npm package as a dependency
the project doesn't need (it already has its own `cn()` in `lib/utils.ts`).
`alert-dialog.tsx`, `sheet.tsx`, and `skeleton.tsx` were all added instead
by running `npx shadcn view <name>` (read-only, writes nothing) to pull the
registry's real Base UI + Tailwind source, then hand-copying it in with
imports pointed at this project's own `@/lib/utils`/`@/components/ui/button`
and the registry's `cn-font-heading`/app-internal icon-helper references
swapped for what this repo actually has (`font-heading`, `lucide-react`).
*Revisit: only after confirming with `--dry-run` that a future CLI version
no longer tries to overwrite existing files unprompted.*

**Retryable errors, not just error messages, 2026-09-04.** `ChatApp.tsx`'s
`error` state carries a `retry` closure alongside the message (a
`PendingState`/`ErrorState` union pair, replacing the previous separate
`pendingPrompt`/`error` booleans) so a "Try again" button can always resend
whatever actually failed — a prompt, or a conversation load — without the
UI re-deriving which action to repeat. `listTrips()`/`getTrip()` in
`backend.ts` got the matching fix on the read side: both used to fail open
to `[]`/`null` on *any* failure, so a plain network blip rendered
identically to "you have no trips" on `/trips` or a hard 404 on
`/trips/[tripId]` — they now return a typed `{ ok, notFound?, error? }`
result, and only a real backend 404 triggers `notFound()`. *Revisit: if a
third request shape is added to `ChatApp`, extend the existing unions
rather than reintroducing parallel booleans.*

**Sidebar mobile drawer uses a real JS breakpoint check (`useIsMobile`,
`useSyncExternalStore`), not a CSS-only hide, 2026-09-04.** Deciding which
of the two sidebar presentations to *mount* — an overlay `Sheet` on mobile
vs. the existing inline collapsible column on desktop, both driven by the
same `sidebarOpen` boolean — has to happen in JS: a `md:hidden` class on a
mounted-but-CSS-hidden Base UI `Dialog` would still leave it "open,"
trapping focus and scroll-locking the page behind an invisible overlay on
desktop. `useSyncExternalStore`, not `useState`+`useEffect`, avoids both
the hydration flicker and this repo's `react-hooks/set-state-in-effect`
lint error the naive version trips. *Revisit: never sidestep this with a
pure-CSS breakpoint hide for a mounted dialog/sheet elsewhere in the app.*

**The "Thinking…" staged-progress text is cosmetic, not real backend
progress, 2026-09-04.** `PendingIndicator.tsx` cycles vague labels
("Reading your trip…", "Checking the weather…") on a client-side timer
because `generateTrip()`'s call to `POST /trips/generate` is still a
single non-streaming request — the backend never tells the client which
stage (classify → generate → weather) it's actually in. Real staged
progress needs that endpoint to become a streaming one (SSE or similar);
that's a backend architecture decision, not something to fake harder on
the frontend. *Revisit: if/when streaming is added, replace the timer with
real stage events rather than layering both.*

**Accessibility pass #2, 2026-09-04 — the recurring bug shape was "state
conveyed only visually."** A manual POUR pass (not the earlier skip-link/
`aria-live`/landmarks pass, a follow-up) found the same underlying issue
in five different components: information a sighted user gets for free
from position or color alone had no programmatic equivalent for
assistive tech. `ChatMessage.tsx`'s speaker (you vs. Itinera) was
left/right position and bubble color only — added an `sr-only` speaker
prefix. `Sidebar.tsx`'s active conversation was color only — added
`aria-current`. `CalendarPushButton.tsx`'s export result (success count
or error) was visible text with no `role="status"`/`"alert"`, so it was
never announced. `ChatInput.tsx`'s composer had a placeholder but no
accessible name (placeholder isn't a reliable label — it disappears once
typed, and isn't always exposed as the field's name at all). `ChatApp.tsx`'s
conversation-loading skeleton is correctly `aria-hidden` (it's decorative)
but that left total silence for a screen reader during the load, so a
sibling `sr-only role="status"` text was added alongside it. *Revisit:
run this same "does this state have anything but a visual cue" check on
any new interactive component — it caught five real instances in
components that otherwise looked fine.*

## Saved Places (auto-persisted, no manual save action)

**Places `find_nearby_places`/`get_place_details` surface for a trip are
persisted automatically the moment the tool call succeeds — no "save this
place" button exists or is planned**, confirmed explicitly with the user
2026-09-04: building manual save would first require structured place
cards in the chat UI (places today are plain prose in the LLM's reply),
real scope beyond persistence alone. `models.SavedPlace`, deduped at the
application level on `(trip_id, name)` (not a DB unique constraint — an
edit turn re-surfacing the same place shouldn't duplicate it).

**`_run_tool_loop` (shared by all three agentic loops) now returns the raw
tool-call results alongside the reply text, not just the text.**
Filtering to "only Places-tool results become a saved place" (never
Wikipedia's `get_place_context`, never the paused currency tool) happens
at the *consumption* site (`routers/trips.py`), not inside the shared
loop — keeps that helper tool-agnostic, matching how it already stayed
agnostic about which of the three loops was calling it.

**Places found *before* a `Trip` row exists (the planning loop runs ahead
of `generate_itinerary` creating one) get threaded through
`generate_itinerary`'s existing result dict as `found_places`, persisted
only once `db.flush()` gives a real `trip.id`.** On the Q&A path, no new
`Trip` is ever created — found places attach to whatever trip already
exists in that conversation (`latest_trip`), or are simply not persisted
if none does yet; never fabricates a trip to hold a place.

## Trip photos (Pexels)

**Pexels, not a second Google Places call** — free tier confirmed live
(200 req/hr, 20,000/month, no card, per Pexels' own docs), and photography
is a different concern from place *data*, so a separate, purpose-built
client (`pexels_client.py`) mirrors `google_places_client.py`'s shape
rather than overloading the Places integration.

**Fetched once per trip, ever — no TTL, unlike weather's 3-hour cache.** A
destination's representative photo doesn't go stale the way a forecast
does; `pexels_service.get_or_refresh_trip_photo` checks only whether
`Trip.photo_url is None`, never a freshness window.

**Query tries `"{destination} city skyline at night"` first, falls back
to the plain destination name only if that returns zero results** —
requested explicitly by the user 2026-09-04 ("I want to see the city
skyline in the night for every place... only if that is not possible").
Live-verified this fallback rarely actually triggers: Pexels' search is
permissive enough to return *something* for almost any real-word query
(even "Yellowstone National Park city skyline at night" found a result),
so "not possible" in practice means a genuinely empty API response, not a
semantic judgment this integration is equipped to make — there's no
vision-based relevance check here, intentionally, matching this
codebase's general anti-fabrication stance (never guess, only use real
data or omit).

**A real schema bug caught by inspecting the live DB, not just tests**:
`main.py`'s `Base.metadata.create_all()` (a documented dev-convenience
safety net) silently created `saved_places` on a dev-server auto-reload
*before* `price_level`'s column width was corrected from `String(20)` to
`String(40)` (Google's own `priceLevel` enum values run up to 26 chars,
e.g. `PRICE_LEVEL_VERY_EXPENSIVE`) — the Alembic migration for the table
alone was silently a no-op against a DB that already had it. Caught by
directly inspecting the live schema post-migration, not by trusting the
migration's exit code; fixed with a follow-up migration. *Revisit: a
useful reminder that `create_all`'s "harmless no-op" claim only holds for
column *existence*, not column *shape* — a model change to an
already-`create_all`'d table always needs a real migration, checked
against the live schema, not assumed to have been a no-op.*

## Persistent tour-guide mode

Once triggered (explicit ask, or a physically-present narrative request —
broadened 2026-09-01 after a live misclassification bug), later `question`
turns keep the fuller narrative style by default until an
`edit_trip`/`new_trip` turn clears it. Real state
(`Conversation.tour_guide_mode`), not a per-turn model judgment. The
activating turn gets a deterministic `"Tour guide mode on."` prefix (code,
not LLM-phrased, for the same reliability reason date arithmetic stays in
code); a UI accent swap (amber) reflects it live.

## Reliability

**Groq automatic fallback** — see LLM provider section above.

## Trip length

**Inferred from the prompt, no UI field.** Explicitly rejected a
slider/number-input; say it in the message instead. Tried and
deliberately removed — don't re-add without a new reason.

## Itinerary export

**.ics only, done; PDF deferred indefinitely.** Deliberately floating
local time (no `TZID`) for the .ics file — Google's live Calendar API,
unlike the file, rejects timed events with no timezone, so the live push
path (`google_calendar.py`) resolves a real IANA timezone via
`weather_service.geocode_timezone()` and the file-export path doesn't
need to. The two-button UI (download `.ics` + separate "Connect Calendar")
was merged into one "Export Plan" button once Calendar scope got bundled
into the base login.

## Deployment (not yet executed)

**Google Cloud Run (backend) + Vercel (frontend)** chosen after a full
cost/cold-start comparison — Cloud Run's Always Free tier is a genuine
permanent allowance, not a shrinking trial, and reuses the Google Cloud
project OAuth already needs. CORS/rate-limiting/per-account daily quota
hardening already shipped ahead of an actual deploy. *Revisit: the OAuth
consent screen publish step (STATUS.md's blockers) is the one piece that
needs a human, and is deliberately not done speculatively before a real
domain exists.*

## `.gitignore` pattern anchoring — a reusable lesson

A gitignore pattern with a slash only at the *end* (`foo/`) floats and
matches at any depth; one with a slash in the *middle* (`foo/*`) anchors
to the directory the `.gitignore` file lives in and won't match a nested
`bar/foo/`. This project has hit both failure directions of that same
rule: the `lib/` shadowing incident (2026-08-26) was a floating pattern
matching too broadly and swallowing `frontend/src/lib/` from git
entirely; `graphify-out/*` (2026-09-02) was an anchored pattern matching
too narrowly and missing a nested `frontend/graphify-out/`. *Revisit:
whenever adding a new ignore pattern for something that could plausibly
exist at more than one depth in the tree — default to the floating form
(`name/`) unless there's a specific reason to anchor it.*

## Git-history secret audit — 2026-09-06

Ran a full-history check (`git log --all -G'<pattern>'` for Google API-key,
OAuth-client-secret, Groq-key, AWS-key, and private-key-header shapes,
plus a name/content review of every historical revision of every
`.env*` file ever tracked) after a frontend-secrets-exposure audit found
no client-side issues. **Result: clean** — no real `.env`/`.env.local`
file, and no hardcoded key/secret value, has ever been committed at any
point in this repo's history, on any branch. Every tracked env-shaped
file (`.env.example`, `.env.share.example`,
`frontend/.env.local.example`) has held only placeholders
(`Paste your API key here`, blank `KEY=`) in every revision, confirmed by
diffing each one's full history, not just its current content.

Found and fixed one real gap while checking: root `.gitignore`'s
`.env` line only matches that exact filename — `.env.local`,
`.env.production`, `backend/.env.local`, etc. were **not** covered
anywhere outside `frontend/.gitignore` (which already has the broader
`.env*` pattern). No such file ever existed, so nothing leaked, but it
was a real hole. Fixed by broadening the root pattern to `.env.*` with
explicit `!.env.example`/`!.env.share.example` negations, plus adding a
defense-in-depth set of common secret-file shapes (`*.pem`, `*.key`,
`*.p12`, `*.pfx`, `*credentials*.json`, `*service-account*.json`) that
weren't yet covered at the repo root either. *Revisit: if a real
`backend/.env` distinct from the root `.env` is ever introduced, confirm
it's still covered — it is today (unanchored root patterns match at any
depth), but re-check after any future `.gitignore` restructuring.*

## Gamification: shareable passport card + seasonal badges — considered, deferred

While designing the onboarding/gamification mockups (see
`docs/design-references.md`), a round of UX research into
Duolingo/Strava/badge-design literature surfaced two real ideas that
didn't make the cut for the current design, kept here so they aren't
silently lost:

- **A one-way shareable passport card** (a read-only link/image of a
  user's passport-stamp collection) — a cheap echo of Strava's kudos/
  social-proof effect (apps with social features show meaningfully
  longer engagement) without needing a followers/friends graph Itinera
  doesn't have and isn't in scope to build.
- **Seasonal/limited-time badges** layered on top of the permanent
  Common→Legendary tier ladder — mirrors Strava's two-tier structure
  (permanent capability badges + event-bound badges), which sustains
  engagement across different user types.

Both are legitimate, research-backed ideas — not rejected on merit, just
out of scope for the current build (no social graph, no $0-budget path
to "seasonal" content generation yet). Revisit if/when a social or
sharing surface is ever considered for Itinera.

The same research pass also confirmed the earlier call to skip a streak
mechanic (see this file's UI/gamification entries in
`docs/design-references.md`): loss-aversion streaks reliably backfire
without a genuine daily-use loop underneath them ("streak creep" —
users optimize for not-losing rather than the actual goal), which
Itinera doesn't have.

## PWA — installable shell live, 2026-09-08; offline trip data explicitly out of scope

STATUS.md had carried "no native/PWA app exists — a real engineering
decision (React Native vs. PWA vs. native) not yet made" as an open item
for a while. User confirmed PWA as the direction and asked for it built;
scoped to two options before writing code — an installable shell
(manifest + a service worker caching only the static app shell) vs. full
offline trip viewing (the above, plus caching a user's own trip/
itinerary data so a saved trip reads with no network). User chose the
installable shell — the smaller, lower-risk first pass.

**What shipped**: `public/manifest.webmanifest` (name, three icon sizes
including one `maskable` variant generated from the existing 512×512
`src/app/icon.png`, `display: "standalone"`), `public/sw.js` (a
service worker that cache-first-serves exactly five static assets —
the manifest, its icons, `favicon.ico` — and passes every other request,
including every page and API call, straight to the network,
untouched), and `PwaRegister.tsx` (a small client component registering
that service worker after `window.load`, deliberately not blocking the
chat UI's own first paint). `layout.tsx`'s metadata gained `manifest`
and Safari's separate `appleWebApp` opt-in (Safari ignores
`manifest.webmanifest` entirely; needs its own meta tags to be
installable at all).

**Deliberately not built — offline trip/itinerary data.** The service
worker never caches `/trips/*` responses, chat history, or anything
per-user; a saved trip is only viewable with a live connection to the
backend, exactly as before this change. Real offline support needs a
genuine data/sync strategy (what happens when a locally-viewed itinerary
and the server's copy disagree, cache invalidation on edit, etc.) that's
a distinct, larger scope from "the app is installable and repeat visits
load faster" — not attempted here.

**Verified live** (not just built): loaded the real dev frontend,
confirmed `document.querySelector('link[rel="manifest"]')` resolves and
`navigator.serviceWorker.getRegistrations()` shows one active
registration scoped to `/`. Frontend suite went 39 → 43 (4 new
`PwaRegister` tests: registers immediately when the page has already
loaded, waits for `load` when it hasn't, renders nothing and never
throws with no `serviceWorker` support at all, and swallows a rejected
registration rather than surfacing it). `tsc --noEmit` and `eslint`
clean.

*Revisit: if/when offline trip viewing becomes a real ask, this shell is
the right foundation to extend (the service worker already exists and is
registered) — but the caching strategy for per-user, server-owned data
is a new design question, not a small addition to `sw.js`'s current
five-asset allowlist.*
