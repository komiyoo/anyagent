from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    status: str
    output: str | None
    error: dict[str, Any] | None
    meta: dict[str, Any]


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._done: dict[str, ToolResult] = {}
        self._inflight: dict[str, asyncio.Task[ToolResult]] = {}

    async def get_done(self, key: str) -> ToolResult | None:
        async with self._lock:
            return self._done.get(key)

    async def set_done(self, key: str, result: ToolResult) -> None:
        async with self._lock:
            self._done[key] = result
            self._inflight.pop(key, None)

    async def get_inflight(self, key: str) -> asyncio.Task[ToolResult] | None:
        async with self._lock:
            return self._inflight.get(key)

    async def set_inflight(self, key: str, task: asyncio.Task[ToolResult]) -> None:
        async with self._lock:
            self._inflight[key] = task

    async def cancel(self, key: str) -> bool:
        async with self._lock:
            task = self._inflight.get(key)
            if task is None:
                return False
            task.cancel()
            return True

