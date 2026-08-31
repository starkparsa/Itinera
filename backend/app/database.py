import os

from sqlalchemy import create_engine, event
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

if DATABASE_URL.startswith("sqlite"):
    # In-memory SQLite (used by tests) needs a shared single connection,
    # otherwise each session sees a fresh, table-less database.
    engine = create_engine(
        DATABASE_URL,
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
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
