import os

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

# Pulls from environment so local dev, Docker, and CI can each point at a
# different database without touching code. Production/dev both use Neon
# Postgres (see CLAUDE.md's "Database: MySQL -> Postgres on Neon" decision
# row, completed 2026-08-29) -- no sensible generic default exists for a
# managed cloud DB (unlike the old local MySQL default this replaced), so
# DATABASE_URL must actually be set; a missing one now fails loudly instead
# of silently pointing at a database that doesn't exist.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy .env.example to .env and set it to your "
        "Neon Postgres connection string (or sqlite:///:memory: for tests, "
        "already handled by conftest.py)."
    )

# The connection the running app actually queries through -- deliberately a
# *different*, lower-privileged Postgres role from DATABASE_URL's own
# schema-owning one (see decisions.md's "Database access control (RLS)"
# entry). DATABASE_URL (neondb_owner) still owns the schema and is what
# Alembic migrates against -- owner privileges (CREATE TABLE, etc.) are
# required there, and Neon's owner role has BYPASSRLS besides, which no
# amount of `FORCE ROW LEVEL SECURITY` can override. APP_DATABASE_URL
# (itinera_app) has neither: it's a normal, non-bypass, non-owner role with
# GRANTed table access, so Postgres' RLS policies actually apply to it.
# Falls back to DATABASE_URL when unset, so local sqlite dev/tests (no role
# concept at all) and any environment that hasn't provisioned the second
# role yet keep working exactly as before -- unenforced, same as today,
# not broken.
APP_DATABASE_URL = os.getenv("APP_DATABASE_URL") or DATABASE_URL

if APP_DATABASE_URL.startswith("sqlite"):
    # In-memory SQLite (used by tests) needs a shared single connection,
    # otherwise each session sees a fresh, table-less database.
    engine = create_engine(
        APP_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite ignores foreign key constraints unless told otherwise, while
    # Postgres (what we actually run in prod) enforces them by default.
    # Without this, the test suite can't catch FK violations -- e.g.
    # deleting a conversation that still has a trip pointing at it would
    # pass here and crash for real against Postgres.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
else:
    engine = create_engine(APP_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Row-level security session identity (see decisions.md's "Database access
# control (RLS)" entry). Every table except `users` is governed by a
# Postgres policy keyed on `app.current_user_id` -- `users` is deliberately
# left out (that entry explains why: /auth/register and /auth/login both
# look a row up by email before any identity exists yet, which RLS can't
# accommodate without a second, bypass-capable Postgres role).
#
# `auth.get_current_user` sets `session.info["rls_user_id"]` on the shared
# request-scoped Session (the same object FastAPI hands to every other
# `Depends(get_db)` in that request) as soon as the user is resolved. This
# hook re-applies whatever is currently in `session.info` at the start of
# *every* transaction on that session -- necessary because a request can
# commit more than once (e.g. an auto-provisioning flush followed by the
# route's own commit), and each commit ends the Postgres transaction that a
# plain one-time `SET LOCAL` would have been scoped to.
#
# `set_config(..., true)` -- the trailing `true` means "local": the value is
# transaction-scoped and is cleared automatically at commit/rollback. That
# matters because connections are pooled and reused across unrelated
# requests -- a session-scoped (`false`) value would leak one request's
# identity into the next request that happens to borrow the same
# connection. The value is always a string, `""` when unset (never Python
# None/NULL), because a bare `current_setting(...)` comparison against NULL
# is always false in SQL either way -- an intentional fail-closed default:
# any query that runs before an identity is set (or an admin/psql session
# that never sets one) sees zero rows in every RLS-governed table, not
# everything.
@event.listens_for(SessionLocal, "after_begin")
def _set_rls_context(session, transaction, connection):
    if connection.dialect.name != "postgresql":
        return  # SQLite (tests) has no RLS concept at all -- nothing to set.
    connection.execute(
        text("SELECT set_config('app.current_user_id', :v, true)"),
        {"v": str(session.info.get("rls_user_id") or "")},
    )


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
