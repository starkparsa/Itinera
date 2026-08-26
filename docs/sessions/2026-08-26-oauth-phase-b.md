# 2026-08-26 — Google OAuth, Phase B (Auth.js + JWT bridge)

**Real Google login is wired end-to-end — Auth.js on the Next.js side,
JWT verification on the FastAPI side — verified live up to the point only
a real Google Cloud OAuth client unlocks.**

## Changes shipped

- `frontend/src/auth.ts`: Auth.js (NextAuth v5 beta) config, Google
  provider, JWT session strategy, `/login` as the sign-in page. `jwt`
  callback persists Google's stable `sub` (via `account.providerAccountId`,
  present only on first sign-in) onto the token explicitly, rather than
  relying on Auth.js's default `user.id` mapping.
- `frontend/src/app/login/page.tsx`: a Server Action form calling
  `signIn("google", { redirectTo: "/" })`.
- `frontend/src/app/page.tsx`: now checks `auth()` server-side and
  redirects to `/login` when unauthenticated, before rendering `ChatApp`.
- `frontend/src/lib/authHeader.ts`: mints a short-lived (60s) HS256 JWT
  from the current session (`sub`, `email` claims) using `jose`, signed
  with `AUTH_BACKEND_SECRET`. Shared by `lib/backend.ts`'s Server Actions
  and the `.ics` export Route Handler — both attach it as
  `Authorization: Bearer <token>` on every backend call now.
- `backend/app/auth.py` (new): `get_current_user` FastAPI dependency,
  verifies that JWT via `python-jose`, looks up `User.google_sub`,
  auto-provisions a new `User` row on first sight of an unrecognized `sub`.
- `backend/app/models.py`: `User.google_sub` column (nullable, unique).
- `backend/alembic/`: introduced (wasn't set up before — `main.py`'s
  `create_all()` can't add a column to an existing table). `env.py` reads
  `DATABASE_URL` the same way every other module does; migration
  `5f96d91ad93a` adds `google_sub`, applied live against the real dev MySQL.
- `routers/trips.py::generate_trip`: now requires
  `Depends(get_current_user)`; the old placeholder-auto-create block is
  gone; every `request.user_id` reference became `user.id`.
  `schemas.TripRequest.user_id` stays in place but unused (formal removal
  is Phase C).
- `backend/tests/conftest.py`: new autouse fixture overriding
  `get_current_user` via `app.dependency_overrides` (the standard
  FastAPI-recommended pattern) so all 144 pre-existing tests keep working
  without needing a real JWT. One existing test
  (`test_question_on_demand_fetch_uses_existing_trip_destination_as_hint`)
  had to be updated — it manually seeded `User(id=1)`/`Conversation(user_id=1)`
  assuming that's "the" API user, which broke once the authenticated user
  came from the override fixture (a different row) instead.
- New `backend/tests/test_auth.py` (9 tests): valid token, auto-provisioning,
  reuse across requests, missing/malformed/expired/wrong-secret tokens,
  missing subject claim, and the unconfigured-secret case (must 500, never
  silently accept any token).

## Bugs found & fixed

- Not a shipped-code bug, but a real test-authoring trap worth recording:
  a pre-existing test hardcoded `user_id=1` when seeding data directly into
  the DB, implicitly assuming that's whatever user the API call would run
  as. Once "the API user" became "whatever `get_current_user`'s override
  returns" (a separate row, since it's looked up by `google_sub`, not id),
  the ownership filter in `generate_trip` correctly 404'd — correct
  behavior, wrong test setup. Fixed by having the test create its own user
  under the exact `google_sub` the conftest override recognizes, imported
  from conftest.py as a shared constant, rather than assuming an id.

## Key learnings

- Confirmed via `node_modules/next-auth/index.d.ts` and
  `@auth/core/providers/google.d.ts` (installed `next-auth@5.0.0-beta.32`,
  still beta as of this session, no stable v5 release yet): the
  `AUTH_{PROVIDER}_{ID|SECRET}` env var naming convention is real and
  auto-inferred, `account.providerAccountId` is the reliable way to get a
  provider's stable subject id in the `jwt` callback, and `next build`
  does **not** require any `AUTH_*` env var to be set (Auth.js validates
  lazily at request time) — meaning the CI frontend-build job needed no
  changes for this phase.
- The Browser-pane's `computer` click action silently failed to submit a
  real `<form action={ServerAction}>` (no request ever left the page,
  confirmed via network log) for reasons unclear — but
  `document.querySelector('form').requestSubmit()` via the JS debugging
  tool worked immediately and drove the flow all the way to
  `accounts.google.com`'s real OAuth endpoint, which correctly rejected the
  placeholder `client_id` with `invalid_client`. That's about as complete a
  live verification as is possible without a real Google Cloud OAuth
  client — everything past that point is entirely Google's own,
  well-established consent/callback flow.
- `alembic revision --autogenerate` correctly detected the new column *and*
  its unique index from `models.py` alone (`unique=True` on the `Column(...)`
  became `create_index(..., unique=True)`) — no manual migration
  authoring needed for this change.

## Open items / follow-ups

- **Real login is not yet possible** without a human creating a Google
  Cloud OAuth client (needs their own Google account) — this is the single
  remaining blocker, can't be done from an agent session.
- Phase C (per-user data isolation) is next: `get_trip`, the `.ics` export
  endpoint, `get_conversation`, `delete_conversation`, and
  `list_conversations` all still run with **zero ownership checks** —
  anyone can read/export/delete anyone else's data by guessing an id, same
  gap the Phase A/B planning audit found, not yet closed.
- `schemas.TripRequest.user_id` still exists on the wire, unused — Phase C
  removes it formally.
- Phase D (Calendar MCP push) unstarted, gated on its own go/no-go check.
