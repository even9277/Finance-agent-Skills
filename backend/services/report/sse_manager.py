"""报告任务 SSE 连接管理。"""

from __future__ import annotations

import asyncio
from typing import Any

MAX_LISTENERS_PER_TASK = 5
QUEUE_MAXSIZE = 32

_sse_connections: dict[str, list[asyncio.Queue]] = {}
_connections_lock = asyncio.Lock()


async def subscribe(task_id: str) -> asyncio.Queue | None:
    async with _connections_lock:
        queues = _sse_connections.setdefault(task_id, [])
        if len(queues) >= MAX_LISTENERS_PER_TASK:
            return None
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        queues.append(queue)
        return queue


async def unsubscribe(task_id: str, queue: asyncio.Queue) -> None:
    async with _connections_lock:
        queues = _sse_connections.get(task_id)
        if not queues:
            return
        if queue in queues:
            queues.remove(queue)
        if not queues:
            _sse_connections.pop(task_id, None)


async def publish(task_id: str, event: str, data: dict[str, Any]) -> None:
    async with _connections_lock:
        queues = list(_sse_connections.get(task_id) or [])
    for queue in queues:
        payload = {"event": event, "data": data}
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass


async def publish_status(task_id: str, status_data: dict[str, Any]) -> None:
    status = status_data.get("status")
    if status == "completed":
        event = "completed"
    elif status == "failed":
        event = "failed"
    else:
        event = "status"
    await publish(task_id, event, status_data)


async def connection_count(task_id: str) -> int:
    async with _connections_lock:
        return len(_sse_connections.get(task_id) or [])


async def clear_connections() -> None:
    async with _connections_lock:
        _sse_connections.clear()
