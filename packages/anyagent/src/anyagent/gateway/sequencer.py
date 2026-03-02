from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


class KeyedSequencer:
    """
    单进程 keyed serialization：同一 key 的任务严格串行执行。
    适用于 v0 单实例/开发环境；多实例需要分布式锁/租约（见 requirements.md#req-7）。
    """

    def __init__(self) -> None:
        self._tails: dict[str, asyncio.Future[None]] = {}
        self._mu = asyncio.Lock()

    async def run(self, key: str, fn: Callable[[], Awaitable[T]]) -> T:
        loop = asyncio.get_running_loop()
        tail = loop.create_future()

        async with self._mu:
            prev = self._tails.get(key)
            self._tails[key] = tail

        if prev is not None:
            await prev

        try:
            return await fn()
        finally:
            if not tail.done():
                tail.set_result(None)
            async with self._mu:
                if self._tails.get(key) is tail:
                    del self._tails[key]

