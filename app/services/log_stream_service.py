from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

# Queue items: str (log line), dict (structured event), or None (done signal)
StreamItem = str | dict[str, Any] | None

_loop: asyncio.AbstractEventLoop | None = None
_subscribers: dict[str, list[asyncio.Queue[StreamItem]]] = defaultdict(list)
_buffers: dict[str, list[StreamItem]] = defaultdict(list)
_finished: set[str] = set()
_BUFFER_MAX = 2000


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe(stream_key: str) -> asyncio.Queue[StreamItem]:
    """Create a queue pre-filled with buffered lines (replay on reconnect)."""
    q: asyncio.Queue[StreamItem] = asyncio.Queue()
    for line in _buffers.get(stream_key, []):
        q.put_nowait(line)
    if stream_key in _finished:
        q.put_nowait(None)
    _subscribers[stream_key].append(q)
    return q


def unsubscribe(stream_key: str, q: asyncio.Queue[StreamItem]) -> None:
    subs = _subscribers.get(stream_key)
    if subs and q in subs:
        subs.remove(q)
    if not _subscribers.get(stream_key):
        _subscribers.pop(stream_key, None)


def _do_publish(stream_key: str, item: StreamItem) -> None:
    """Must be called from within the event loop."""
    if item is not None:
        buf = _buffers[stream_key]
        buf.append(item)
        if len(buf) > _BUFFER_MAX:
            del buf[: len(buf) - _BUFFER_MAX]
    else:
        _finished.add(stream_key)
    for q in list(_subscribers.get(stream_key, [])):
        q.put_nowait(item)


def publish(stream_key: str, line: str) -> None:
    """Thread-safe publish. Works from both async and sync (thread-pool) contexts."""
    try:
        asyncio.get_running_loop()
        _do_publish(stream_key, line)
    except RuntimeError:
        if _loop is not None:
            _loop.call_soon_threadsafe(_do_publish, stream_key, line)


def publish_event(stream_key: str, event: str, data: dict[str, Any]) -> None:
    """Publish a named SSE event (e.g. html_iteration). Thread-safe."""
    if not stream_key:
        return
    item: dict[str, Any] = {"_event": event, **data}
    try:
        asyncio.get_running_loop()
        _do_publish(stream_key, item)
    except RuntimeError:
        if _loop is not None:
            _loop.call_soon_threadsafe(_do_publish, stream_key, item)


def publish_done(stream_key: str) -> None:
    """Signal end-of-stream to all subscribers."""
    if not stream_key:
        return
    try:
        asyncio.get_running_loop()
        _do_publish(stream_key, None)
    except RuntimeError:
        if _loop is not None:
            _loop.call_soon_threadsafe(_do_publish, stream_key, None)
