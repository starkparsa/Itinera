# Manual auth testing: real signed-in click-through

**Status: a human-run runbook, not automated — and that's a deliberate
choice, not a placeholder for one.** Run this before a release, or
whenever code on the login/auth path changes.

## Why this isn't a pytest fixture or an E2E suite

Two separate things have both been called "the auth testing gap" across
this project's history, and only one of them was ever actually missing:

- **Backend auth mocking for automated tests already exists.**
  [`backend/tests/conftest.py`](../backend/tests/conftest.py)'s
  `override_auth()` fixture (`autouse=True`) swaps
  [`auth.get_current_user`](../backend/app/auth.py) for a fixed test user
  via `app.dependency_overrides` — every backend test already runs fully
  "signed in," with zero JWT/Google involvement. There is nothing to build
  here.
- **The real remaining gap is a genuine browser OAuth click-through**, and
  it can't be meaningfully automated. This app's BFF architecture means
  Auth.js ([`frontend/src/auth.ts`](../frontend/src/auth.ts)) is the
  *only* real OAuth client — it talks to Google directly and mints a
  short-lived (~60s) HS256 JWT server-side
  ([`frontend/src/lib/mintBackendJwt.ts`](../frontend/src/lib/mintBackendJwt.ts)).
  FastAPI never talks to Google; it only ever verifies that JWT. No
  Playwright/Cypress config exists in this repo (only Vitest, for
  unit/component tests). Mocking Google's own consent screen would mean
  standing up new E2E infrastructure to test a screen that isn't this
  app's code at all — disproportionate for what it would actually prove.

So: the backend gap is closed already, and the frontend gap is closed
here, by hand, on a real Google account.

## What this verifies

That a brand-new Google identity can sign in and have every downstream
piece of state — user provisioning, onboarding, Calendar credentials —
actually land correctly, which nothing in the automated suite exercises
end to end (each piece is unit-tested against a fake token instead).

## Prerequisites

- A real Google account you control, **not your personal one** — a plus-
  addressed alias on an account you own (e.g.
  `youraddress+itineratest@gmail.com`) works fine for a real OAuth flow
  and keeps this test account clearly separate.
- A real Google Cloud OAuth client configured per
  [`README.md`](../README.md)'s prerequisites (`AUTH_GOOGLE_ID`/
  `AUTH_GOOGLE_SECRET` set, redirect URI registered, Calendar API enabled).
- Both servers running locally (`docker compose up --build`, or the two
  `npm run dev` / `uvicorn` terminals — see `README.md`'s "Running the
  app" section for either path).
- To use a Google account that's never signed into this app before (or
  has had its Calendar grant revoked at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions))
  — a returning, already-consented account skips the consent screen this
  test exists to exercise.

## Steps

1. Navigate to `http://localhost:3000`. Confirm it redirects to `/login`
   (an unauthenticated visitor should never see the chat UI).
2. Click "Continue with Google," sign in with the test account, and
   click through Google's real consent screen (the one this test exists
   to exercise — it should ask for profile/email + Calendar access, per
   `auth.ts`'s configured scope).
3. Confirm you land back on the chat UI, not `/login` and not an error
   page.
4. Open the profile page (`/profile`, or the sidebar link) and confirm
   the onboarding dialog fires once for this new account. Step through it
   and save — confirm the save succeeds against the real backend (a
   toast, no inline error) and that a "Skip for now" or a later edit
   round-trips correctly.
5. Confirm the trip planning flow works: ask for a trip in chat, confirm
   an itinerary generates and the Trip Hub page loads it.

## Verifying the backend state directly

Connect to whichever database `DATABASE_URL` points at (Neon Postgres in
the default path, or a local SQLite file if using the zero-setup dev
path) and run:

```sql
-- A User row was auto-provisioned with a real google_sub (not a test
-- fixture's stand-in value).
SELECT id, google_sub, email, display_name FROM users
  WHERE email = 'youraddress+itineratest@gmail.com';

-- The onboarding save from step 4 actually persisted.
SELECT user_id, onboarding_completed_at, onboarding_skipped_at
  FROM user_profiles WHERE user_id = <id from above>;

-- The Calendar scope grant round-tripped -- proves auth.ts's jwt
-- callback successfully POSTed real tokens to
-- /auth/google-calendar-token, not just that login itself worked.
SELECT user_id, created_at FROM google_calendar_credentials
  WHERE user_id = <id from above>;
```

All three should return exactly one row for this run. If the third query
comes back empty, the login itself likely still worked (steps 1–5 above
would pass) but the Calendar credential save silently failed — check the
Next.js server console for the `"Failed to save Google Calendar
credentials"` log line `auth.ts`'s `jwt` callback emits on that path.

## What this doesn't cover

This is a smoke test for the login path itself, not a full regression
suite — day-to-day feature changes are still covered by the automated
backend/frontend test suites. Re-run this specifically when auth-adjacent
code changes (`auth.ts`, `mintBackendJwt.ts`, `backend/app/auth.py`,
`backend/app/routers/auth.py`) or before a release to a real domain.
