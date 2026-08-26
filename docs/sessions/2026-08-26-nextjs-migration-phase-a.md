# 2026-08-26 — Next.js migration, Phase A (of the Google OAuth + Calendar plan)

**Replaced the Streamlit frontend with a Next.js (App Router, TypeScript)
app reaching full UI parity, as Phase A of a four-phase plan to add Google
OAuth login and Google Calendar push.**

## Changes shipped

- New `frontend/` (Next.js 16, React 19, TypeScript) replaces
  `frontend/streamlit_app.py` entirely. Feature parity confirmed live
  against the real backend and real conversation data: sidebar chat
  history (list/select/new/delete), per-day itinerary rendering with
  weather icons and both °C/°F, and both `.ics` export buttons (inline +
  persistent top-of-chat) with the same start_date-gating rule.
- `lib/backend.ts`: Server Actions are the only code that calls FastAPI —
  the browser never talks to it directly, matching the existing "frontend
  is a thin client" principle. No auth yet; every call still runs under the
  backend's placeholder user, exactly as before.
- `app/api/trips/[tripId]/calendar/route.ts`: a Route Handler that proxies
  the `.ics` download (byte-for-byte verified against the backend's real
  output) — a Server Action's JSON-only return shape doesn't fit a binary
  file download, a Route Handler does.
- Docker: new multi-stage `frontend/Dockerfile` using Next.js's
  `output: "standalone"`; `docker-compose.yml`'s frontend port changed from
  Streamlit's `8501` to Next.js's default `3000`. `.github/workflows/ci.yml`
  gained a `frontend-lint-and-build` job (npm ci, lint, build) alongside the
  existing backend job; `build-and-push`'s matrix build already covered
  `frontend` generically and needed no change.
- No backend changes in this phase — deliberately, to validate the rewrite
  independently of auth risk (see the plan).

## Bugs found & fixed

None — this was a rewrite, not a fix. One real gotcha, not a bug: Next.js
16's `next dev`/`next build` auto-generates `AGENTS.md`/`CLAUDE.md` in the
frontend directory by default (a framework feature for agents working with
a newer Next.js than their training data) — set `agentRules: false` in
`next.config.ts` since this repo already has its own root `CLAUDE.md` as
the single source of truth.

## Key learnings

- Next.js 16 postdates this session's training cutoff for some framework
  specifics — before writing code, read `node_modules/next/dist/docs/`
  (which the auto-generated `AGENTS.md` explicitly points at). Confirmed no
  breaking surprises for what this phase needed (Server Actions, Route
  Handlers with async `params`, `output: "standalone"`), but worth
  repeating this check for anything more advanced in later phases (Auth.js
  integration, middleware).
- Next.js's own Server Actions security docs are directly relevant to
  Phase C's ownership-check retrofit: "Treat every action as an untrusted
  entry point... a client legitimately tells the server *which* item to
  act on, but it should not supply the row's contents or ownership" — this
  is the exact same principle behind removing `TripRequest.user_id` as a
  client-trusted field, just phrased from Next.js's side of the fence.
- The Browser-pane's `computer` `type` action can garble text into an
  existing textarea value (confirmed in an earlier session on the Streamlit
  UI) — `form_input` (sets the value directly, dispatches proper React
  events) is the reliable way to fill a form field when testing.

## Open items / follow-ups

- Phases B (Auth.js + JWT bridge + `User.google_sub` + Alembic), C
  (ownership-check retrofit — four endpoints currently have **no**
  user-scoping at all, found during this planning pass), and D (Calendar
  MCP push, gated on a go/no-go check of whether `google-genai`'s MCP
  support has graduated past "experimental") are designed but not started.
  See CLAUDE.md's decision log ("Auth" row) for the full plan.
- No frontend test suite yet (Streamlit had none either) — worth adding
  once the component structure stabilizes past Phase A, rather than writing
  tests against UI that Phase B/C will still touch.
