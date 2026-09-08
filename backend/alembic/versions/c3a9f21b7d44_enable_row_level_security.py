"""enable row-level security on every user-owned table except users

Revision ID: c3a9f21b7d44
Revises: 0668d9be3ecf
Create Date: 2026-09-08

See decisions.md's "Database access control (RLS)" entry for the full
reasoning. Summary:

- Every table here is owned by the single backend Postgres role (created
  them via Alembic), so `ENABLE ROW LEVEL SECURITY` alone would be a no-op
  for that role -- `FORCE ROW LEVEL SECURITY` is required to actually
  apply policies to the table owner, not just other roles.
- `users` is deliberately EXCLUDED from this migration. /auth/register and
  /auth/login (routers/auth.py) both look a row up by email before any
  request identity exists at all -- that's structurally what "login"
  means -- which RLS can't accommodate on a single shared Postgres role
  without a second, bypass-capable role (real added infra, out of scope
  for now). Account-level protection there still comes from the existing
  email/google_sub unique constraints, bcrypt hashing, and get_current_user's
  exact-match lookups -- unchanged by this migration.
- Every table below is either directly `user_id`-owned, or one FK hop from
  a `user_id`-owned table (messages -> conversations, itinerary_items/
  saved_places -> trips) -- policies for the latter use an EXISTS subquery
  against the owning table's own `user_id`.
- `current_setting(..., true)` returns NULL, not an error, when nothing
  has been set for the session -- comparing any column against NULL is
  always false in SQL, so a code path that forgets to set the session
  identity (or a raw psql/admin session that never does) fails closed,
  seeing zero rows, rather than leaking everything.

IMPORTANT for anyone touching this database directly (psql, a one-off
admin script, a future migration's data backfill): once this migration is
applied, a plain connection as the backend's own role sees NO rows in any
of the tables below unless it first runs
`SELECT set_config('app.current_user_id', '<id>', false);` in that
session. This is the intended effect of FORCE ROW LEVEL SECURITY, not a
bug -- see this file's downgrade() if that's actively blocking something
urgent.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3a9f21b7d44"
down_revision = "0668d9be3ecf"
branch_labels = None
depends_on = None

# Tables whose ownership is a direct user_id column.
_DIRECT_OWNER_TABLES = [
    "conversations",
    "trips",
    "user_profiles",
    "google_calendar_credentials",
    "user_stats",
    "user_achievements",
]

# (table, owning_table, fk_column) for tables one FK hop from a
# user_id-owned table.
_FK_HOP_TABLES = [
    ("messages", "conversations", "conversation_id"),
    ("itinerary_items", "trips", "trip_id"),
    ("saved_places", "trips", "trip_id"),
]


def upgrade() -> None:
    for table in _DIRECT_OWNER_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_owner_access ON {table}
            USING (user_id::text = current_setting('app.current_user_id', true))
            WITH CHECK (user_id::text = current_setting('app.current_user_id', true))
            """
        )

    for table, owning_table, fk_column in _FK_HOP_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_owner_access ON {table}
            USING (
                EXISTS (
                    SELECT 1 FROM {owning_table} o
                    WHERE o.id = {table}.{fk_column}
                    AND o.user_id::text = current_setting('app.current_user_id', true)
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM {owning_table} o
                    WHERE o.id = {table}.{fk_column}
                    AND o.user_id::text = current_setting('app.current_user_id', true)
                )
            )
            """
        )


def downgrade() -> None:
    for table, _owning_table, _fk_column in _FK_HOP_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_access ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in _DIRECT_OWNER_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_access ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
