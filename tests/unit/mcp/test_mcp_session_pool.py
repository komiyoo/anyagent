from __future__ import annotations

import asyncio
from typing import Any

import pytest

from anyagent.mcp import manager as manager_module
from anyagent.mcp.manager import MCPServerManager
from anyagent.mcp.models import MCPConfig
from anyagent.mcp.session_pool import MCPStdioConnectionPool


class _FakeStdioServer:
    """Minimal stdio-like MCP server tracking connect/disconnect calls."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.connect_calls = 0
        self.disconnect_calls = 0
        self._connected = False

    async def ensure_connected(self) -> None:
        if not self._connected:
            self.connect_calls += 1
            self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "do", "description": "", "inputSchema": {"type": "object", "properties": {}}}]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": f"{self.name}:{name}"}], "is_error": False}

    def is_idle(self, now: float) -> bool:
        _ = now
        return False


def test_pool_reuses_connection_for_same_key() -> None:
    async def _run() -> None:
        pool = MCPStdioConnectionPool(max_size=8)
        created: list[_FakeStdioServer] = []

        def _factory() -> Any:
            server = _FakeStdioServer("calc")
            created.append(server)
            return server

        key = ("main", "calc", "sess-1")
        first = await pool.acquire(key, _factory)
        second = await pool.acquire(key, _factory)

        assert first is second
        assert len(created) == 1  # factory only called on miss
        assert first.connect_calls == 1

    asyncio.run(_run())


def test_pool_separates_by_session_key() -> None:
    async def _run() -> None:
        pool = MCPStdioConnectionPool(max_size=8)

        def _factory() -> Any:
            return _FakeStdioServer("calc")

        a = await pool.acquire(("main", "calc", "sess-1"), _factory)
        b = await pool.acquire(("main", "calc", "sess-2"), _factory)

        assert a is not b
        assert len(pool) == 2

    asyncio.run(_run())


def test_pool_evicts_lru_and_disconnects() -> None:
    async def _run() -> None:
        pool = MCPStdioConnectionPool(max_size=2)
        servers: dict[str, _FakeStdioServer] = {}

        def _make(session: str) -> Any:
            def _factory() -> Any:
                server = _FakeStdioServer(session)
                servers[session] = server
                return server

            return _factory

        s1 = await pool.acquire(("main", "calc", "s1"), _make("s1"))
        await pool.acquire(("main", "calc", "s2"), _make("s2"))
        # Touch s1 so s2 becomes the LRU entry.
        await pool.acquire(("main", "calc", "s1"), _make("s1"))
        # Inserting a third entry evicts the LRU (s2), not s1.
        await pool.acquire(("main", "calc", "s3"), _make("s3"))

        assert len(pool) == 2
        assert servers["s2"].disconnect_calls == 1
        assert servers["s1"].disconnect_calls == 0
        assert s1.disconnect_calls == 0

    asyncio.run(_run())


def test_pool_cleanup_all_disconnects_everything() -> None:
    async def _run() -> None:
        pool = MCPStdioConnectionPool(max_size=8)
        made: list[_FakeStdioServer] = []

        def _factory() -> Any:
            server = _FakeStdioServer("calc")
            made.append(server)
            return server

        await pool.acquire(("main", "calc", "s1"), _factory)
        await pool.acquire(("main", "calc", "s2"), _factory)
        await pool.cleanup_all()

        assert len(pool) == 0
        assert all(server.disconnect_calls == 1 for server in made)

    asyncio.run(_run())


def test_pool_size_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_STDIO_POOL_SIZE", "5")
    assert MCPStdioConnectionPool().max_size == 5
    monkeypatch.setenv("MCP_STDIO_POOL_SIZE", "not-an-int")
    assert MCPStdioConnectionPool().max_size == 256


def test_manager_routes_stdio_servers_through_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        built: list[_FakeStdioServer] = []

        def _fake_create(*, name: str, config: Any, agent_id: str, credential_store: Any) -> Any:
            _ = config, agent_id, credential_store
            server = _FakeStdioServer(name)
            built.append(server)
            return server

        monkeypatch.setattr(manager_module, "create_mcp_server", _fake_create)

        pool = MCPStdioConnectionPool(max_size=8)
        manager = MCPServerManager(
            agent_id="main",
            mcp_config=MCPConfig.model_validate({"mcpServers": {"calc": {"command": "run-calc"}}}),
            stdio_pool=pool,
        )

        # stdio server config is held aside, not eagerly instantiated into _servers.
        assert manager._servers == {}
        assert "calc" in manager._stdio_configs

        tools = await manager.list_all_tools(session_key="s1")
        result = await manager.call_tool("mcp.calc.do", {}, session_key="s1")

        assert tools[0]["name"] == "mcp.calc.do"
        assert "calc:do" in result
        # One pooled connection reused across list + call within the same session.
        assert len(built) == 1
        assert len(pool) == 1

    asyncio.run(_run())


def test_manager_keeps_http_servers_out_of_pool() -> None:
    pool = MCPStdioConnectionPool(max_size=8)
    manager = MCPServerManager(
        agent_id="main",
        mcp_config=MCPConfig.model_validate({"mcpServers": {"web": {"url": "https://example.com/mcp"}}}),
        stdio_pool=pool,
    )

    assert sorted(manager._servers) == ["web"]
    assert manager._stdio_configs == {}
