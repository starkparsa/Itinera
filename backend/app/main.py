from dotenv import load_dotenv

# Must run before any sibling module is imported -- database.py,
# llm_service.py, agent_service.py, and tools.py all read config via
# os.getenv() at import time. Walks up from this file's directory to find
# the repo-root .env, so it works regardless of the process's cwd. No-ops
# harmlessly in Docker/CI, where real env vars are already set and no .env
# file is present in the image.
load_dotenv()

import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import conversations, trips

# Retry logic to wait for database to be ready
max_retries = 10
retry_delay = 2  # seconds

for attempt in range(max_retries):
    try:
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before deploying publicly
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trips.router)
app.include_router(conversations.router)


@app.get("/health")
def health():
    return {"status": "ok"}
