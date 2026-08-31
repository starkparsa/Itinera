from dotenv import load_dotenv

# Must run before any sibling module is imported -- database.py,
# llm_service.py, agent_service.py, and tools.py all read config via
# os.getenv() at import time. Walks up from this file's directory to find
# the repo-root .env, so it works regardless of the process's cwd. No-ops
# harmlessly in Docker/CI, where real env vars are already set and no .env
# file is present in the image.
load_dotenv()

import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .database import Base, engine
from .rate_limit import limiter
from .routers import auth, conversations, trips

# Retry logic to wait for database to be ready
max_retries = 10
retry_delay = 2  # seconds

for attempt in range(max_retries):
    try:
        # Only ever creates missing *tables* -- harmless no-op against a DB
        # that already has them (real dev/prod MySQL). Schema *changes* to
        # existing tables (e.g. the google_sub column, see auth.py) go
        # through Alembic (backend/alembic/) instead, run manually
        # ("alembic upgrade head") -- this call staying here is what lets a
        # fresh SQLite test DB or a brand-new MySQL instance still work with
        # zero setup.
        Base.metadata.create_all(bind=engine)
        break
    except Exception:
        if attempt < max_retries - 1:
            print(f"Database not ready, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_delay)
        else:
            print(f"Failed to connect to database after {max_retries} attempts")
            raise

app = FastAPI(title="AI Travel Planner API")

# ALLOWED_ORIGINS: comma-separated list of exact origins allowed to call this
# API from a browser (e.g. "https://app.example.com,https://staging.example.com").
# Was a bare "*" wildcard -- meant any origin's JavaScript could call this
# authenticated API directly (a real security-review finding, see
# docs/security-review.md). Nothing in this app's own architecture actually
# needs a browser to call it cross-origin at all -- the frontend is a thin
# client that only ever reaches the backend from Next.js Server Actions
# (frontend/src/lib/backend.ts), never from code running in the user's
# browser -- so a tight allow-list here costs the legitimate app nothing and
# closes off a real attack surface (a malicious page driving a stolen bearer
# token straight at this API, or scripted credential-stuffing against
# get_current_user). Defaults to the local Next.js dev server so
# `docker compose up`/local dev keep working with zero config; production
# MUST set this explicitly to its real deployed frontend origin(s) -- see
# docs/deployment-guide.md.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [origin.strip() for origin in _allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Rate limiting (slowapi) -- see rate_limit.py's module docstring for the
# full rationale (real cost/flood risk, IP-keyed, in-process-only caveat).
# SlowAPIMiddleware applies `limiter.default_limits` to every route
# automatically; routes that need a tighter limit (e.g. POST /trips/generate)
# get their own @limiter.limit(...) decorator instead, which the middleware
# defers to rather than double-applying.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(trips.router)
app.include_router(conversations.router)
app.include_router(auth.router)


@app.get("/health")
def health():
    return {"status": "ok"}
