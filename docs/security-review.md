# Security review: manual pass findings

**Status: advisory, findings only — nothing here has been fixed yet.
Written 2026-08-30 by manual code inspection (grep + read), not a
dedicated security-scanning skill — none is installed, see note below.**

## On tooling

No installed skill is dedicated to security review, and none was
available to add. The actual right tool for this is **`/code-review
ultra`** — a multi-agent cloud review of the current branch (or
`/code-review ultra <PR#>` for a specific PR). It's user-triggered and
billed, so it can't be launched from here — run it yourself whenever you
want a deeper, multi-agent pass than this manual one. `/ultrareview` is a
deprecated alias for the same thing.

This document is a first pass done by hand: grepping for the classic
injection/footgun patterns (raw SQL string interpolation, `eval`/`exec`,
`dangerouslySetInnerHTML`, unescaped shell calls, SSRF-prone URL building)
and reading the auth/request-validation code paths directly. It found real
things; it is not a substitute for `/code-review ultra` or a real pentest
before handling anyone's data but your own.

## What's already solid (checked, not just assumed)

- **No raw SQL anywhere** — every query goes through SQLAlchemy's ORM/query
  builder. No `f"SELECT ... {user_input}"`-shaped string ever reaches a
  cursor. Classic SQL injection isn't reachable here.
- **No `eval`/`exec`/`pickle.load`/`yaml.load`/`os.system`/`subprocess`**
  anywhere in `backend/app/`.
- **No `dangerouslySetInnerHTML`, `eval`, or `new Function`** anywhere in
  `frontend/src/` — React's default JSX escaping is doing its job
  untouched, no deliberate opt-out of it exists.
- **JWT verification is done correctly**
  ([`backend/app/auth.py`](../backend/app/auth.py)): explicit
  `algorithms=["HS256"]` allow-list (no "alg: none" / algorithm-confusion
  hole), a missing signing secret fails the request loudly (500) rather
  than silently accepting unverified tokens, and the minted token itself
  ([`frontend/src/lib/mintBackendJwt.ts`](../frontend/src/lib/mintBackendJwt.ts))
  carries a real 60-second expiry that `python-jose` enforces on decode.
- **Every outbound HTTP call uses a hardcoded hostname** (Open-Meteo,
  Frankfurter, Wikipedia) with user-derived values only ever passed via
  `requests`' `params=` dict or `requests.utils.quote()` — never
  string-concatenated into the URL itself. No SSRF surface: an attacker
  can't redirect any of these calls to an internal address via a crafted
  destination/place name.
- **Ownership checks are real, not cosmetic** — every trip/conversation
  endpoint filters by `user_id == user.id` from the verified JWT (see
  `CLAUDE.md`'s Auth Phase C row), and a cross-user id correctly 404s
  rather than 403ing (doesn't even confirm the id exists to someone who
  doesn't own it) — confirmed by reading `routers/trips.py` and
  `routers/conversations.py` directly, not just trusting the changelog.
- **`.ics` calendar export uses the `icalendar` library's `.add()` API
  throughout**, never raw string concatenation into event text — RFC 5545
  escaping/folding is handled for you, no CRLF-injection-into-calendar-file
  risk from item text.
- **Calendar OAuth tokens are encrypted at rest** (`cryptography.fernet`,
  `google_calendar.py`) — a compromised database wouldn't hand over usable
  refresh tokens directly.

## Real findings

### 1. Raw exception messages returned to the client (medium)

Four places return `str(exc)`/an f-string containing the raw exception
straight into the HTTP response body:

- [`routers/trips.py:211`](../backend/app/routers/trips.py#L211) — `detail=f"LLM failed to answer: {exc}"`
- [`routers/trips.py:282`](../backend/app/routers/trips.py#L282) — `detail=f"LLM generation failed: {exc}"`
- [`routers/trips.py:344`](../backend/app/routers/trips.py#L344) — `detail=f"Failed to save trip: {exc}"`
- [`routers/auth.py:34`](../backend/app/routers/auth.py#L34) — `detail=str(exc)`

Not a code-execution risk, but real information disclosure — a raw
exception can include library internals, partial file paths, or (in the
worst case) a fragment of a connection string or credential embedded in a
driver's own error message. Standard fix: log the full exception
server-side (`logger.exception(...)`, already done in at least one of
these spots) and return a fixed, generic message to the client instead of
interpolating `{exc}` into it.

### 2. No API-level rate limiting (medium, cost-relevant here specifically)

Every request-throttling reference found in the codebase is Gemini's own
internal 429-detection (`llm_service.py`/`groq_service.py`'s
`_is_rate_limited`) — that's about reacting to a quota already exhausted,
not preventing abuse. Nothing limits how often an authenticated user (or a
buggy client, or a compromised/leaked JWT) can call `/trips/generate`,
each hit of which is 2+ real Gemini calls. For this app specifically, that
means the same 20-requests/day free-tier wall already documented in
`CLAUDE.md` as a *development* annoyance becomes a real *denial-of-service
vector against your own quota* once anyone besides you can reach it. Worth
a simple per-user rate limit (`slowapi` is the common FastAPI-native
choice) before a real public deployment, not necessarily before that.

### 3. No length cap on the prompt field (low-medium)

[`schemas.py`](../backend/app/schemas.py)'s `TripRequest.prompt: str` has
no `max_length`. Combined with #2, an attacker (or just a careless client)
could send an enormous prompt on every request, multiplying real Gemini
token cost with no server-side ceiling. A `Field(max_length=2000)` (or
whatever a real trip request reasonably needs) is a one-line fix.

### 4. `/docs`, `/redoc`, `/openapi.json` are open by default (informational)

`FastAPI(title="AI Travel Planner API")` in
[`main.py`](../backend/app/main.py) doesn't set `docs_url=None`/
`openapi_url=None`. Not a vulnerability by itself — plenty of real APIs
keep interactive docs public on purpose — but it does mean your full
request/response schema (every field name, every endpoint) is public
the moment the backend has a real URL. Worth a conscious yes/no, not a
default-by-omission.

## Already flagged elsewhere, not repeated in detail here

- CORS `allow_origins=["*"]` — see `docs/deployment-readiness.md` §1.1,
  the highest-priority item in that doc already.
- Secrets living in a plain `.env` for local dev — same doc, §1.4.

## Suggested order

1. CORS fix + exception-detail fix (#1 above) — both quick, both belong in
   the same "before deploying publicly" pass as the CORS item already
   flagged in `deployment-readiness.md`.
2. `max_length` on `TripRequest.prompt` (#3) — one line, no dependency on
   anything else.
3. Decide `/docs` exposure (#4) — a product decision, not a bug; make it
   consciously either way.
4. Rate limiting (#2) — the most involved of the four, worth doing once a
   real deployment target is picked (ties into whatever the host's own
   request limits/pricing look like).
5. Run `/code-review ultra` for a deeper pass than this manual one caught.
