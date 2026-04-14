from __future__ import annotations

from fastapi import FastAPI

from app.api.agent import router as agent_router
from app.api.pipeline import router as pipeline_router
from app.db.database import init_db

app = FastAPI(title="Pingula Core Service", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(pipeline_router)
app.include_router(agent_router)
