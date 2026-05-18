from __future__ import annotations

import asyncio
from typing import Any

from anyagent.mcp.manager import MCPServerManager
from anyagent.mcp.models import MCPConfig
from anyagent.observability import ObservabilitySink, get_observability_emitter
from anyagent.protocol.observability import ObservabilityEvent


class _MemorySink(ObservabilitySink):
    def __init__(self) -> None:
        self.events: list[ObservabilityEvent] = []

    def emit(self, event: ObservabilityEvent) -> None:
        self.events.append(event)


class _FakeMCPServer:
    name = "calc"

    async def ensure_connected(self) -> None:
        return None

    async def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "sum", "description": "", "inputSchema": {"type": "object", "properties": {}}}]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": f"{name}:{arguments.get('a')}"}], "is_error": False}

    async def disconnect(self) -> None:
        return None

    def is_idle(self, now: float) -> bool:
        _ = now
        return False


def test_mcp_manager_emits_observability_events_for_list_and_call() -> None:
    async def _run() -> None:
        sink = _MemorySink()
        emitter = get_observability_emitter()
        emitter.configure([sink])
        try:
            manager = MCPServerManager(
                agent_id="main",
                mcp_config=MCPConfig.model_validate({"mcpServers": {"calc": {"url": "https://example.com/mcp"}}}),
            )
            manager._servers = {"calc": _FakeMCPServer()}  # type: ignore[assignment]

            tools = await manager.list_all_tools()
            result = await manager.call_tool("mcp.calc.sum", {"a": 1})

            assert tools[0]["name"] == "mcp.calc.sum"
            assert "sum:1" in result
            assert [item.event for item in sink.events] == [
                "mcp.server.connected",
                "mcp.tools.listed",
                "mcp.tool.called",
            ]
            assert sink.events[0].payload["agent_id"] == "main"
            assert sink.events[1].payload["tool_count"] == 1
        finally:
            emitter.configure([])

    asyncio.run(_run())


def test_mcp_manager_skips_disabled_servers() -> None:
    manager = MCPServerManager(
        agent_id="main",
        mcp_config=MCPConfig.model_validate(
            {
                "mcpServers": {
                    "enabled": {"url": "https://enabled.example.com/mcp"},
                    "disabled": {"enabled": False, "url": "https://disabled.example.com/mcp"},
                }
            }
        ),
    )

    assert sorted(manager._servers) == ["enabled"]
