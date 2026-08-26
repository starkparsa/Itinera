# 2026-08-26 — Google OAuth, Phase D (Calendar push) — plan complete

**All four phases of the Google OAuth + Calendar plan are now code-complete.
A live go/no-go check reversed the originally-planned Calendar MCP approach
in favor of `googleapiclient`, and a real, unrelated bug in `alembic/env.py`
was found and fixed before it could do damage.**

## Changes shipped

- **Go/no-go check** (per the plan, run before writing any client code):
  live web search confirmed `google-genai`'s MCP support is still
  explicitly "experimental" (Google's own SDK docs/GitHub), and the
  Calendar MCP server itself is gated behind Google's Workspace Developer
  Preview Program, not GA. Used the named fallback, `googleapiclient`,
  against Calendar API v3 directly — also the better architectural fit
  independent of the experimental status (a Calendar push is a
  deterministic user click, not a Gemini judgment call).
- `backend/app/google_calendar.py` (new): encrypts/decrypts tokens at rest
  (`cryptography.fernet`, new `TOKEN_ENCRYPTION_KEY`), upserts credentials
  (preserving an existing refresh token when Google doesn't re-issue one),
  refreshes an expired access token automatically and persists the
  refresh, and pushes one event per itinerary item — reusing
  `calendar_export.resolve_event_time` (renamed from the module-private
  `_event_start_time` specifically for this reuse) so the `.ics` export
  and a live Calendar push can never disagree about what time an event
  lands at.
- `models.GoogleCalendarCredential` (new table, one row per user who's
  granted Calendar access) + Alembic migration `f0fa120ecdf7`.
- `POST /trips/{id}/push-to-calendar` (`routers/trips.py`): same ownership
  check as every other trip endpoint, `428` when the user hasn't connected
  Calendar (distinct from a real failure), `502` on a genuine Calendar API
  error.
- `routers/auth.py` (new): `POST /auth/google-calendar-token` (saves
  tokens — called server-side by the frontend right after Google grants
  the scope, never reached by the browser) and `GET
  /auth/google-calendar-status` (lets the UI show "Connect" vs. "Push"
  without guessing from a failed attempt).
- Frontend: incremental OAuth consent — `frontend/src/auth.ts`'s base
  Google provider requests no extra scopes at plain login;
  `connectGoogleCalendarAction` (`lib/authActions.ts`) requests the
  Calendar scope only when the user clicks "Connect Google Calendar",
  via a one-off `authorizationParams` override on that specific `signIn`
  call. `auth.ts`'s `jwt` callback saves the resulting tokens to the
  backend the moment Google returns them. New `CalendarPushButton.tsx`,
  wired into both `TripView` (inline, per generated trip) and the
  persistent top-of-chat control, same `start_date`-required gating as
  the `.ics` export button.
- New `lib/mintBackendJwt.ts`: pure JWT-signing function extracted out of
  `authHeader.ts` so `auth.ts`'s `jwt` callback (which can't easily call
  `auth()` on itself mid-callback) and `authHeader.ts` (which reads the
  session first) share one signing implementation instead of two.
- 16 new backend tests: `test_google_calendar.py` (encryption round-trip,
  credential upsert semantics, token refresh, push logic) and
  `test_calendar_push_router.py` (all the new endpoints' status codes,
  including cross-user 404 and the not-connected 428). Full suite: 175
  tests pass.

## Bugs found & fixed

- **A real, unrelated bug**, not part of this phase's actual scope:
  `backend/alembic/env.py`'s `from app import models` — needed only for
  its side effect of registering every table on `Base.metadata` before
  `target_metadata = Base.metadata` is read — had been silently deleted by
  an earlier session's `ruff --fix` run (correctly flagged as "unused"
  since nothing in that file references `models` by name). This made
  `target_metadata` effectively empty. First attempt at this phase's
  migration (`alembic revision --autogenerate`) produced a script that
  would have **dropped every table in the database** — `users`,
  `conversations`, `trips`, `messages`, `itinerary_items` — and never even
  mentioned the new table it was supposed to add. Caught by reading the
  generated migration file before running it (never assume `--autogenerate`
  output is correct without reading it), not by any test. Fixed with a
  `# noqa: F401` and a comment explaining the import is for its side
  effect; regenerated the migration correctly (confirmed via a direct
  `Base.metadata.tables.keys()` check before and after) and verified the
  real dev database's existing tables were untouched.

## Key learnings

- `datetime.utcnow().timestamp()` is a classic gotcha that bit a test
  here: `.timestamp()` on a **naive** datetime assumes **local time**, not
  UTC, even though `utcnow()`'s naive value represents UTC wall-clock
  time. A test constructing "1 hour ago" as a Unix timestamp this way
  produced a value silently offset by the machine's local UTC offset,
  making an intentionally-expired token look non-expired. Fixed by using
  `time.time()` directly for real Unix timestamps in tests. The actual
  production code path was never affected — `google_calendar.py` only ever
  receives a real Unix timestamp from Auth.js's `account.expires_at`, it
  never derives one from a naive datetime itself.
- Confirmed live (via web search, not memory) that `google-genai`'s MCP
  support and the Calendar MCP server's Developer Preview status hadn't
  changed since CLAUDE.md's original Aug 2026 notes — worth re ­verifying
  facts like this at the point they actually matter, exactly as the
  project's own stated discipline requires, rather than assuming a dated
  note is still current.

## Open items / follow-ups

- **Not yet tested with a real Google account** — every phase (B, C, D)
  was verified as far as possible without one, up to Google's own
  `invalid_client` rejection of placeholder OAuth credentials. A human
  needs to: create a real Google Cloud OAuth client, enable the Google
  Calendar API on that project, and generate `TOKEN_ENCRYPTION_KEY` in
  `.env` before a real end-to-end click-through (login → generate a trip →
  push to calendar → see the real event) is possible.
- No UI surfaces for *disconnecting* Calendar access or viewing what's
  been pushed — out of scope for this round, flagged for later if it comes
  up in real use.

## Follow-up, same day: merged into one "Export Plan" button, consent bundled into login

After getting real OAuth credentials working (verified live up to Google's
actual "Sign in to continue to Travel-Planner" screen), you asked to
simplify: since Calendar push is about to be the *only* export path, why
keep a separate `.ics` button and a separate "Connect Google Calendar"
step at all?

- `frontend/src/auth.ts`: the Calendar scope
  (`https://www.googleapis.com/auth/calendar.events`) moved from the
  incremental `connectGoogleCalendarAction` override onto the **base**
  Google provider config. `access_type: "offline"` stays; `prompt:
  "consent"` deliberately does **not** move with it — forcing that on
  every login would trade one friction point for another. A genuinely
  first-ever login still shows Google's consent screen naturally (nothing
  to skip yet), which is exactly when `access_type=offline` earns us a
  refresh token; a returning user's login is recognized as
  already-consented and skips straight through, same as before this
  change. Verified live: the very first login redirect's query string now
  includes `scope=openid+email+profile+...calendar.events` — one consent
  screen, not two.
- `connectGoogleCalendarAction` (`lib/authActions.ts`) is no longer the
  common path — it's now a recovery fallback for when a stored credential
  goes stale (the 7-day refresh-token cap Google applies to an unverified/
  "Testing"-status OAuth app, or a manually revoked grant), triggered
  automatically by `CalendarPushButton` when a push comes back "not
  connected."
- `CalendarPushButton.tsx`: dropped the connected/not-connected label
  branching. Always renders **"Export Plan"**; clicking it always
  attempts the real push first (no upfront `calendarConnected` gate), only
  falling back to reconnection on an actual 428 from the backend.
- The old `.ics` download button (`ExportButton.tsx`) is deleted from the
  UI entirely — both placements (inline per-trip, persistent top-of-chat)
  now render only `CalendarPushButton`. The backend capability it used
  (`calendar_export.py`, `GET /trips/{id}/calendar.ics`, and the frontend's
  proxy Route Handler) is untouched and still works if hit directly —
  nothing in the UI just links to it anymore.
- `page.tsx`/`ChatApp.tsx`/`TripView.tsx`/`ChatMessage.tsx`: the
  `calendarConnected` prop threaded through all of them for the old
  connect/push branching is gone, along with the `getGoogleCalendarStatus()`
  fetch that fed it — `CalendarPushButton` no longer needs it.

**One real caveat flagged, not fixed**: this Google Cloud project is
presumably still in OAuth "Testing" publishing status, which caps refresh
tokens at 7 days regardless of use — a stored Calendar credential will
stop working on its own after a week and need the reconnect fallback
above, independent of anything in this app. Fixing that for real means
publishing the OAuth consent screen to Production in Google Cloud Console
— a manual step, not something to build around speculatively now.

## Second follow-up, same day: real first click-through found a real bug

Once real OAuth credentials actually worked (after adding the developer's
own account as a Test user on the OAuth consent screen -- Testing-status
apps reject anyone not explicitly listed, a separate gate from having
valid client credentials at all), the very first real "Export Plan" click
failed with `Google Calendar API error: Missing time zone definition for
start time`.

**Root cause**: `calendar_export.py`'s `.ics` export deliberately uses
floating local time with no `TZID` -- valid RFC 5545, and calendar apps
reading an `.ics` file handle it fine. Google Calendar's REST API does
*not* extend that same tolerance to a live `events.insert` call: a timed
(`dateTime`) event with no `timeZone` field and no UTC offset embedded in
the string is rejected outright. This was an untested assumption in the
original Phase D design -- `google_calendar.py` reused
`calendar_export.resolve_event_time`'s hour/minute output but never added
a timezone, on the (wrong) premise that the same floating-time approach
would carry over.

**Fix**: `weather_service.geocode_timezone()` (new) -- Open-Meteo's
geocoding search response already includes a `"timezone"` field per
result (confirmed live via a direct `curl` to the geocoding endpoint for
"Miami" -> `"America/New_York"`), so this costs zero extra API calls
beyond a lookup the app already does elsewhere for weather. `google_calendar.py`
now sets `timeZone` on every timed event's `start`/`end`, falling back to
`"UTC"` only if geocoding itself fails (a neutral default, never a
fabricated specific zone). All-day (`date`) events are untouched --
`timeZone` doesn't apply to them and Google's API doesn't expect one.

5 new tests added (`test_geocode_timezone_*` in `test_weather_service.py`;
timezone-inclusion, all-day-has-no-timezone, and UTC-fallback in
`test_google_calendar.py`). Full suite: 180 tests pass.

**Key learning**: a design decision correctly justified for one output
format (`.ics`, RFC 5545) doesn't automatically transfer to a different
API surface (Google's REST Calendar API) consuming conceptually similar
data -- this was reused code (`resolve_event_time`) doing exactly what it
was built to do, but the *timezone* assumption around it needed
re-verifying per-surface, not carried over from the first place it was
established. Only found by an actual live click-through, not by the
existing mocked test suite (which never exercised the real Calendar API's
validation rules) -- another point for this project's own stated
discipline of verifying live before considering something done.
