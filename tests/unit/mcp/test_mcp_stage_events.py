from __future__ import annotations

import asyncio
from typing import Any

from anyagent.mcp.manager import MCPServerManager
from anyagent.mcp.models import MCPConfig, MCPServerConfig
from anyagent.protocol.stage_events import StageEvent


class _LifecycleServer:
    name = "calc"

    def __init__(self, *, fail: bool = False) -> None:
        self.config = MCPServerConfig.model_validate({"url": "https://example.com/mcp"})
        self._connected = False
        self.fail = fail

    async def ensure_connected(self) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self._connected = True

    async def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "sum", "inputSchema": {"type": "object", "properties": {}}}]

    async def disconnect(self) -> None:
        self._connected = False

    def is_idle(self, now: float) -> bool:
        _ = now
        return False


def test_mcp_lifecycle_stage_events_start_ready_and_dedupe() -> None:
    async def _run() -> None:
        events: list[StageEvent] = []

        async def _sink(event: StageEvent) -> None:
            events.append(event)

        manager = MCPServerManager(
            agent_id="main",
            mcp_config=MCPConfig.model_validate({"mcpServers": {"calc": {"url": "https://example.com/mcp"}}}),
        )
        manager._servers = {"calc": _LifecycleServer()}  # type: ignore[assignment]

        await manager.list_all_tools(stage_event_sink=_sink, response_id="resp_1")
        await manager.list_all_tools(stage_event_sink=_sink, response_id="resp_1")

        assert [event.type for event in events] == [
            "anyagent.mcp.server.starting",
            "anyagent.mcp.server.ready",
        ]
        assert events[0].response_id == "resp_1"
        assert events[0].server_label == "calc"
        assert events[0].transport == "streamable_http"

    asyncio.run(_run())


def test_mcp_lifecycle_stage_events_failed() -> None:
    async def _run() -> None:
        events: list[StageEvent] = []

        async def _sink(event: StageEvent) -> None:
            events.append(event)

        manager = MCPServerManager(
            agent_id="main",
            mcp_config=MCPConfig.model_validate({"mcpServers": {"calc": {"url": "https://example.com/mcp"}}}),
        )
        manager._servers = {"calc": _LifecycleServer(fail=True)}  # type: ignore[assignment]

        tools = await manager.list_all_tools(stage_event_sink=_sink, response_id="resp_1")

        assert tools == []
        assert [event.type for event in events] == [
            "anyagent.mcp.server.starting",
            "anyagent.mcp.server.failed",
        ]
        assert events[1].error is not None
        assert events[1].error.message == "boom"

    asyncio.run(_run())
