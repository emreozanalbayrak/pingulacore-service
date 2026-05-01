from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.schemas.api import CreateStreamKeyResponse
from app.services import log_stream_service

router = APIRouter(prefix="/v1", tags=["logs"])

_KEEPALIVE_TIMEOUT = 20.0


@router.post(
    "/stream-keys",
    response_model=CreateStreamKeyResponse,
    dependencies=[Depends(get_current_user)],
)
async def create_stream_key() -> CreateStreamKeyResponse:
    return CreateStreamKeyResponse(stream_key=str(uuid.uuid4()))


@router.get("/logs/stream/{stream_key}")
async def stream_logs(stream_key: str) -> StreamingResponse:
    q = log_stream_service.subscribe(stream_key)

    async def generate():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_TIMEOUT)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    yield f"event: done\ndata: {{}}\n\n"
                    break
                if isinstance(item, dict):
                    event_name = item.get("_event", "message")
                    payload = {k: v for k, v in item.items() if k != "_event"}
                    yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
                else:
                    yield f"data: {json.dumps({'line': item})}\n\n"
        finally:
            log_stream_service.unsubscribe(stream_key, q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
