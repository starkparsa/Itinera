import os

# Must run before app.database is imported anywhere -- swaps the DB target
# to an in-memory SQLite so tests don't need a live MySQL instance (CI runs
# this without spinning up a database container).
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
