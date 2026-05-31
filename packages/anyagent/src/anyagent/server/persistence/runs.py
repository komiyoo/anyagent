from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(slots=True)
class RunHandle:
    response_id: str
    task: asyncio.Task[None]
    cancelled: bool = False


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}
        self._lock = asyncio.Lock()

    async def add(self, *, response_id: str, task: asyncio.Task[None]) -> None:
        async with self._lock:
            self._runs[response_id] = RunHandle(response_id=response_id, task=task)

    async def cancel(self, response_id: str) -> bool:
        async with self._lock:
            handle = self._runs.get(response_id)
            if handle is None:
                return False
            handle.cancelled = True
            handle.task.cancel()
            return True

    async def remove(self, response_id: str) -> None:
        async with self._lock:
            self._runs.pop(response_id, None)
