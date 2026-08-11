import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

# Pulls from environment so local dev, Docker, and CI can each point at a
# different MySQL instance without touching code.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://travel_user:travel_pass@localhost:3306/travel_planner",
)

if DATABASE_URL.startswith("sqlite"):
    # In-memory SQLite (used by tests) needs a shared single connection,
    # otherwise each session sees a fresh, table-less database.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
