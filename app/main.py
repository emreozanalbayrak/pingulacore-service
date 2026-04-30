from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.explorer import router as explorer_router
from app.api.agent import router as agent_router
from app.api.legacy import router as legacy_router
from app.api.logs import router as logs_router
from app.api.pipeline import router as pipeline_router
from app.db.database import init_db
from app.services.auth_service import seed_admin_if_needed
from app.services.log_stream_service import set_event_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    seed_admin_if_needed()
    set_event_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="Pingula Core Service", version="0.1.0", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(pipeline_router)
app.include_router(agent_router)
app.include_router(logs_router)
app.include_router(explorer_router)
app.include_router(legacy_router)
