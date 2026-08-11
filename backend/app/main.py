from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import trips

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


@app.get("/health")
def health():
    return {"status": "ok"}
