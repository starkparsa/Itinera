# 2026-08-26 — Google OAuth, Phase C (per-user data isolation)

**Every endpoint now enforces real ownership — the four gaps found during
the original planning audit are closed, and the trust-boundary bug
(`TripRequest.user_id` as a client-supplied field) is fully removed, not
just unused.**

## Changes shipped

- `routers/trips.py::get_trip` and `::export_trip_calendar`: added
  `Depends(get_current_user)` and a `Trip.user_id == user.id` filter
  (previously plain `Trip.id`-only lookups — anyone could read or export
  any trip by guessing its id).
- `routers/conversations.py::get_conversation` and `::delete_conversation`:
  same fix, `Conversation.user_id == user.id`. `::list_conversations`: its
  client-supplied `user_id` query param (`DEFAULT_USER_ID = 1`) — exactly
  as untrustworthy as the old `TripRequest.user_id` field — replaced with
  the authenticated caller's own id.
- All five now return `404` (not `403`) on a cross-user id, so a request
  doesn't even confirm the id exists to someone who doesn't own it.
- `schemas.TripRequest.user_id` removed entirely (Phase B had already
  stopped reading it but left the field in place; this phase deletes it).
- New `backend/tests/test_ownership_isolation.py` (6 tests): simulates two
  different logged-in users by swapping `app.dependency_overrides[get_current_user]`
  mid-test, and confirms a captured id from one user's data 404s for the
  other across all five endpoints, plus a regression guard that a
  client-supplied `user_id` in the request body has zero effect.

## Bugs found & fixed

None new this phase — this *was* the fix for the four gaps found during
Phase A/B's planning audit (see those session logs).

## Key learnings

- No frontend changes were needed for this phase: `lib/backend.ts` never
  sent a `user_id` anywhere (Phase B already switched every call to the
  JWT-based auth header), so removing the field from the backend schema was
  a pure backend-side tightening with zero coordination required.
- Verified live against the running Docker stack, not just the test suite:
  every one of the five endpoints (`POST /trips/generate`, `GET /trips/{id}`,
  `GET /trips/{id}/calendar.ics`, `GET /conversations`, `GET
  /conversations/{id}`, `DELETE /conversations/{id}`) now correctly returns
  `401 Missing bearer token` with no `Authorization` header at all — auth is
  enforced at the transport level, not just logically correct in code that
  happens to pass tests.

## Open items / follow-ups

- Phase D (Calendar MCP push) is next and last — gated on a live go/no-go
  check of whether `google-genai`'s MCP support has graduated past
  "experimental" before writing any client code against it.
- Real login is still blocked on a human creating a Google Cloud OAuth
  client (`AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET`) — unrelated to this
  phase's work, carried over from Phase B.
