from dotenv import load_dotenv

# Must run before any sibling module is imported -- database.py,
# llm_service.py, agent_service.py, and tools.py all read config via
# os.getenv() at import time. Walks up from this file's directory to find
# the repo-root .env, so it works regardless of the process's cwd. No-ops
# harmlessly in Docker/CI, where real env vars are already set and no .env
# file is present in the image.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import conversations, trips

# For local dev this creates tables directly. Once the schema stabilizes,
# switch to `alembic upgrade head` and drop this line -- migrations should
# own schema changes so history is tracked in git.
Base.metadata.create_all(bind=engine)

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
