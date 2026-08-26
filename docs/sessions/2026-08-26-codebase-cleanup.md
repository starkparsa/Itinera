# 2026-08-26 — Codebase cleanup pass

**A full parse of both `backend/` and `frontend/` for dead code and build
inefficiencies, following the Google OAuth + Calendar work shipped earlier
today — this is CLAUDE.md build-order item 1's "ongoing discipline," not a
one-time step.**

## What was checked

`ruff check .` (backend), `npm run lint` + `npx tsc --noEmit` (frontend)
all passed clean going in — this project has stayed tidy as it's built, so
the pass focused on what those tools structurally can't see: cross-file
dead exports (a function/route with zero callers anywhere), unused
dependencies, stale files, and Docker build hygiene. Read every file under
`backend/app/`, `backend/tests/`, and `frontend/src/` end to end (not just
grepped) to confirm this.

## Bugs found & fixed

- **Six frontend files were never actually in version control, since the
  very first commit.** `git ls-files frontend/src/lib/` came back empty --
  `authActions.ts`, `authHeader.ts`, `backend.ts`, `mintBackendJwt.ts`,
  `types.ts`, and `weatherIcon.ts` (the Server Actions that call FastAPI,
  the whole JWT-minting/auth-bridge logic, and the shared TypeScript
  types) all existed only on this local disk. Root cause: the root
  `.gitignore`'s generic Python-packaging section has a bare `lib/` line
  (meant to ignore a Python build's `lib/` output directory) -- gitignore
  patterns with no leading slash match at *any* depth, so it was also
  silently swallowing `frontend/src/lib/` the whole time. Confirmed via
  `git log --all -- frontend/src/lib/backend.ts` (zero commits, any
  branch) and `.gitignore`'s own history (`lib/` present since "Initial
  commit"). Practical impact: anyone cloning this repo fresh, or any CI
  run that checks out from GitHub rather than building from this
  session's local disk, would get a `frontend/` that's missing these
  imports entirely -- `next build` would fail immediately on `Module not
  found: Can't resolve '@/lib/backend'` and five others just like it. Every
  local Docker rebuild and every "full suite passes" claim in this
  session's earlier work was against local disk, which still had the real
  files -- this would not have been caught by any of that, only by an
  actual fresh clone or a real CI run against `origin`. Fixed by
  anchoring the pattern to the repo root (`/lib/`, `/lib64/` -- scoped to
  match only a *root-level* `lib/`, which this project never produces
  anyway) and `git add`-ing all six files for the first time. Verified: a
  full `next build` still succeeds with the files now tracked, and a scan
  of every other tracked directory (`backend/app`, `backend/tests`,
  `frontend/src`) for the same shadowing pattern turned up nothing else --
  this was the only collision.

## Changes shipped

- **`frontend/src/lib/backend.ts`**: removed `getGoogleCalendarStatus()` --
  a Server Action wrapper with zero callers anywhere in the app, left over
  from before the same-day "Export Plan" button merge (see the Auth
  decision-log row). Confirmed via repo-wide grep before removing.
- **`backend/.dockerignore`** (new -- backend had none at all): excludes
  `.venv`, `__pycache__`, `.pytest_cache`, `tests/`, and other dev-only
  paths from the build context. Concrete, measured effect: `docker build
  ./backend`'s context dropped from including a 261MB `.venv` directory to
  772 bytes transferred. None of this was ever `COPY`'d into the image --
  the Dockerfile only ever copies `requirements.txt` and `app/` -- so this
  was pure wasted upload/hash time on every build, not a functional bug.
- **`backend/requirements.txt`** split: `pytest` and `httpx` moved out to
  a new **`backend/requirements-dev.txt`** (`-r requirements.txt` plus the
  two test-only packages). The backend Docker image was installing a test
  runner and an HTTP test client into the production container for no
  runtime reason -- neither is imported by anything under `app/`. `.github/
  workflows/ci.yml` and `README.md` updated to install both files for
  linting/testing; `backend/Dockerfile` needed no change since it already
  only ever installed `requirements.txt`.
- Verified all three changes together: full test suite still **180
  passed** (via `backend/.venv`'s interpreter -- the system `python` on
  this machine isn't the project's venv and is missing `python-jose`,
  worth remembering next time a command run outside Docker mysteriously
  fails to import something that's clearly in `requirements.txt`), frontend
  lint/typecheck still clean, and a real `docker build ./backend` still
  succeeds and installs exactly the runtime package set (confirmed
  `pytest`/`httpx` absent from the installed list, everything else intact).

## What was found but deliberately left alone

Two things looked unreachable but turned out to be **intentional**
retentions from earlier today's "Export Plan" merge, not oversights --
confirmed with you before touching either, since removing a documented
product decision is a scope change CLAUDE.md's own header calls out,
not a mechanical cleanup:

- `GET /trips/{trip_id}/calendar.ics` (backend) and its Next.js proxy
  (`app/api/trips/[tripId]/calendar/route.ts`) -- nothing in the UI links
  to either anymore (`ExportButton.tsx` is gone), but both still work if
  hit directly, and were kept on purpose per the Auth decision-log row's
  Phase D follow-up.
- `GET /auth/google-calendar-status` (backend) -- its only frontend caller
  was the `getGoogleCalendarStatus()` function removed above, but the
  endpoint itself is real, tested (`test_calendar_push_router.py`), and
  cheap to keep as a status-introspection capability for a future UI (a
  settings page, say) that wants to show connection state without
  guessing from a failed push.

**Decision: keep both, trim only the dead frontend wrapper** (see above).
Re-litigate only if a future cleanup pass finds these still have zero
callers *and* nothing plausible would use them -- not the case today.

## Key learnings

- A missing `.dockerignore` doesn't fail a build or show up in any lint
  tool -- it only shows up as a slow, oversized build context, which is
  easy to never notice locally if Docker's build cache is warm. Worth a
  `.dockerignore` check on any project's *first* real cleanup pass, not
  just when something visibly breaks.
- `backend/.venv`'s Python isn't on this machine's default `PATH` --
  running `python`/`pytest` directly resolves to a system Python 3.13
  install that's missing project dependencies (`python-jose`, confirmed
  live via a real `ModuleNotFoundError`). Use `backend/.venv/Scripts/
  python.exe` (Windows) explicitly for anything outside Docker/CI.
- `datetime.utcnow()`/`datetime.utcfromtimestamp()` are deprecated as of
  Python 3.12+ and now emit a real `DeprecationWarning` on every test run
  (360 of them across this suite) -- **not fixed here**, since CLAUDE.md's
  `pyproject.toml` already documents naive UTC datetimes as this
  project's deliberate, project-wide convention (the `DTZ` ruff rule is
  explicitly ignored for this reason). Swapping every call site to
  timezone-aware datetimes is a real architectural decision, not a
  cleanup-pass fix -- flagged here for whenever that decision gets made
  deliberately, not applied piecemeal now.

## Open items / follow-ups

- CLAUDE.md's top-of-file "Current state" summary still said weather "was
  removed outright... and stays removed," which contradicted its own
  later decision-log entry (Open-Meteo weather has been live since
  2026-08-25). Fixed as part of this pass -- see CLAUDE.md's Backend
  bullet.
- The `datetime.utcnow()` deprecation warnings above are silent today
  (naive datetimes still work in 3.12/3.13) but will become a real port
  cost whenever the runtime Python version advances far enough for the
  removal to land -- worth a dedicated pass, not a side effect of the next
  unrelated change.
