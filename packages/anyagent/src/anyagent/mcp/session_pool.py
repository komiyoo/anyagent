from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from collections.abc import Callable

from .server import MCPServer

logger = logging.getLogger("anyagent.mcp")

#: Pool key: (agent_id, server_label, session_key). session_key may be None for
#: anonymous (sessionless) requests, which then share one bucket per server.
PoolKey = tuple[str, str, str | None]

_DEFAULT_POOL_SIZE = 256
_POOL_SIZE_ENV = "ANYAGENT_MCP_STDIO_POOL_SIZE"


def _resolve_pool_size() -> int:
    raw = os.getenv(_POOL_SIZE_ENV)
    if raw is None:
        return _DEFAULT_POOL_SIZE
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_POOL_SIZE
    return value if value > 0 else _DEFAULT_POOL_SIZE


class MCPStdioConnectionPool:
    """LRU-bounded pool of stdio MCP server connections keyed by (agent, server, session).

    Only stdio transports are pooled here, since each stdio connection owns a child
    process and is expensive to keep around unbounded. HTTP/SSE servers are cheap and
    stay owned by their manager. When the pool exceeds ``max_size`` the least-recently
    used connection is evicted and gracefully disconnected (closing its child process).
    """

    def __init__(self, *, max_size: int | None = None) -> None:
        self._max_size = max_size if (max_size is not None and max_size > 0) else _resolve_pool_size()
        self._entries: "OrderedDict[PoolKey, MCPServer]" = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def max_size(self) -> int:
        return self._max_size

    def __len__(self) -> int:
        return len(self._entries)

    async def acquire(self, key: PoolKey, factory: Callable[[], MCPServer]) -> MCPServer:
        """Returns a connected stdio server for ``key``, creating it on miss.

        ``factory`` builds a fresh (unconnected) ``MCPServer`` and is only invoked on a
        cache miss. The returned server is guaranteed connected. Eviction of the LRU
        entry happens after insertion so the pool never exceeds ``max_size``.
        """
        async with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                self._entries.move_to_end(key)
                await existing.ensure_connected()
                return existing

            server = factory()
            await server.ensure_connected()
            self._entries[key] = server
            self._entries.move_to_end(key)
            await self._evict_to_capacity_locked()
            return server

    async def _evict_to_capacity_locked(self) -> None:
        while len(self._entries) > self._max_size:
            evicted_key, evicted_server = self._entries.popitem(last=False)
            await self._disconnect_safely(evicted_server, evicted_key)

    @staticmethod
    async def _disconnect_safely(server: MCPServer, key: PoolKey) -> None:
        try:
            await server.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("mcp stdio pool ignored one disconnect failure", extra={"pool_key": key}, exc_info=True)

    async def cleanup_all(self) -> None:
        """Disconnects every pooled connection and clears the pool."""
        async with self._lock:
            entries = list(self._entries.items())
            self._entries.clear()
        for key, server in entries:
            await self._disconnect_safely(server, key)
