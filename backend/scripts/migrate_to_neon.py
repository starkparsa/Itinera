"""One-off data migration: copy every row from the current Docker MySQL
database into a fresh Neon Postgres database, preserving primary keys.

Not a general-purpose tool -- a scratch script for this specific
MySQL -> Postgres cutover (see CLAUDE.md's "Database: MySQL -> Postgres on
Neon" decision row, 2026-08-29). Safe to delete once the migration is
confirmed and Docker MySQL is decommissioned.

Usage:
    SOURCE_DATABASE_URL=mysql+pymysql://travel_user:travel_pass@localhost:3307/travel_planner \\
    TARGET_DATABASE_URL=postgresql+psycopg2://...neon.tech/travel_planner?sslmode=require \\
    backend/.venv/Scripts/python.exe backend/scripts/migrate_to_neon.py

Prerequisites:
    - The target Postgres database must already have the current schema
      (run `Base.metadata.create_all()` -- i.e. just start the app once
      against TARGET_DATABASE_URL -- then `alembic stamp head`, the same
      "brand-new DB" convention documented in main.py/README.md).
    - Target tables must be empty (this script does not upsert or dedupe).
"""

import os
import sys

from sqlalchemy import create_engine, select, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import (
    Conversation,
    GoogleCalendarCredential,
    ItineraryItem,
    Message,
    Trip,
    User,
)

# Copy order matters -- parents before children, so foreign keys always
# resolve against rows that already exist in the target.
TABLES_IN_FK_ORDER = [User, Conversation, Trip, Message, ItineraryItem, GoogleCalendarCredential]


def main() -> None:
    source_url = os.environ.get("SOURCE_DATABASE_URL")
    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not source_url or not target_url:
        print("Set both SOURCE_DATABASE_URL and TARGET_DATABASE_URL environment variables.", file=sys.stderr)
        raise SystemExit(1)

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)

    with source_engine.connect() as src, target_engine.begin() as dst:
        for model in TABLES_IN_FK_ORDER:
            table = model.__table__
            rows = src.execute(select(table)).mappings().all()
            if not rows:
                print(f"{table.name}: 0 rows, skipping")
                continue
            dst.execute(table.insert(), [dict(r) for r in rows])
            print(f"{table.name}: copied {len(rows)} rows")

        # Explicit-PK inserts don't advance Postgres's serial sequences --
        # without this, the next real INSERT (no explicit id) would try to
        # reuse id=1 and collide with the row just migrated.
        for model in TABLES_IN_FK_ORDER:
            table = model.__table__
            seq_name = f"{table.name}_id_seq"
            dst.execute(
                text(
                    f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM {table.name}), 1), "
                    f"(SELECT MAX(id) FROM {table.name}) IS NOT NULL)"
                )
            )
        print("Sequences reset to match migrated data.")

    print("Migration complete.")


if __name__ == "__main__":
    main()
