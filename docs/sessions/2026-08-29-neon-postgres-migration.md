# 2026-08-29 — MySQL to Neon Postgres migration

**Executed the already-decided-but-never-done "MySQL -> Postgres on Neon"
migration, directly prompted by the same-day MySQL reconciliation mess
(see `2026-08-29-mysql-reconciliation.md`) making "stable" the explicit
ask.**

## Changes shipped

- User created the Neon project/account (not something Claude does --
  account creation is out of scope) and handed over the connection string.
- Schema created on the fresh Neon database via the existing `main.py`/
  `README.md`-documented convention for a brand-new DB:
  `Base.metadata.create_all()` then `alembic stamp head` (not `upgrade
  head` -- there's no base-schema migration to run through, only deltas
  assuming a pre-Alembic starting schema).
- New `backend/scripts/migrate_to_neon.py` -- one-off script, copies every
  row from Docker MySQL to Neon Postgres table-by-table in FK order
  (`users -> conversations -> trips -> messages -> itinerary_items ->
  google_calendar_credentials`), preserving primary keys, then resets
  Postgres's serial sequences (explicit-PK inserts don't advance them).
- `backend/app/database.py`: `DATABASE_URL` is now **required** -- raises
  a clear `RuntimeError` if unset, instead of silently defaulting to a
  local MySQL URL that may not even exist. Comments updated MySQL -> Postgres
  throughout (FK-enforcement-by-default comparison, etc.).
- `backend/requirements.txt`: added `psycopg2-binary==2.9.12`. Kept
  `pymysql` for now -- still needed by the migration script's source-side
  read; remove once Docker MySQL is decommissioned.
- `docker-compose.yml`: `backend`'s `DATABASE_URL` now passes through from
  `.env` (`${DATABASE_URL}`) instead of a hardcoded
  `mysql+pymysql://...@mysql:3306/...` string; dropped `depends_on: mysql`.
  The local `mysql` service itself is kept, not deleted, but moved behind
  a `legacy-mysql` Compose profile so it's not started by default.
- `.env` / `.env.example` / `README.md` / `CLAUDE.md`: all updated to
  describe Postgres/Neon as the actual database, not MySQL.

## Bugs found & fixed

- **`create_all()` silently created zero tables and reported success.**
  First schema-creation attempt did `from app.database import Base,
  engine; Base.metadata.create_all(bind=engine)` without also importing
  `app.models` -- so `Base.metadata` had no tables registered on it at
  all (`Base` alone doesn't know about any model class until something
  imports the module that defines them, a pure Python side effect).
  `create_all()` against empty metadata is a legitimate no-op: creates
  nothing, raises nothing, prints nothing wrong. This is the *exact same
  class of bug* CLAUDE.md already documents for `alembic/env.py`'s
  `from app import models  # noqa: F401` import -- caught this time only
  because the next step (querying `information_schema.tables` directly)
  didn't trust the script's own "Schema created." message. Fixed by
  importing `app.models` first; re-ran and confirmed all 6 tables actually
  existed before proceeding to `alembic stamp head` and the data copy.

## Key learnings

- `Base.metadata.create_all()`'s silent-no-op-on-empty-metadata behavior
  is a real footgun worth remembering generally, not just for
  `alembic/env.py` -- any one-off script that imports `Base`/`engine`
  directly (bypassing `main.py`, which already does the correct import
  order) needs to import the models module too, and it's worth verifying
  the actual DB state afterward rather than trusting a "success" print.
- Neon's pooled connection endpoint (`...-pooler.<region>.aws.neon.tech`,
  PgBouncer in front of the real Postgres instance) worked fine for this
  migration's plain synchronous SQLAlchemy usage -- no session-level
  features (prepared statements, advisory locks, etc.) were needed that
  would have required the direct (non-pooled) endpoint instead.

## Open items / follow-ups

- Docker MySQL (`docker compose --profile legacy-mysql up mysql`) is kept
  running for now as a live backup of the pre-migration data, not
  stopped/removed this session -- revisit once the team is confident Neon
  is solid.
- `pymysql` stays in `requirements.txt` until Docker MySQL is actually
  decommissioned and `backend/scripts/migrate_to_neon.py` is deleted.
- The native Windows MySQL80 service (the original red herring from the
  reconciliation session) was never touched by this work either -- still
  whatever unrelated state it was in before.
