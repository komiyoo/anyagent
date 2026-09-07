from __future__ import annotations

import asyncio
from typing import Any

from anyagent.mcp.manager import MCPServerManager
from anyagent.mcp.models import MCPConfig, MCPServerConfig
from anyagent.mcp.server import MCPServer
from anyagent.mcp.util import mcp_tool_to_function_param, sanitize_mcp_tool_name
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam


class _FakeMCPServer:
    name = "demo"

    def __init__(self) -> None:
        self.called_names: list[str] = []

    async def ensure_connected(self) -> None:
        return None

    async def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "Read File!",
                "description": "Read a file",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.called_names.append(name)
        return {"content": [{"type": "text", "text": name}], "is_error": False}

    async def disconnect(self) -> None:
        return None

    def is_idle(self, now: float) -> bool:
        _ = now
        return False


class _FilterServer(MCPServer):
    async def create_streams(self) -> Any:
        raise AssertionError("not used")


def test_sanitize_mcp_tool_name_normalizes_to_function_safe_name() -> None:
    assert sanitize_mcp_tool_name("Read File!") == "read_file"
    assert sanitize_mcp_tool_name("ALPHA.beta-1") == "alpha.beta-1"


def test_mcp_tool_to_function_param_keeps_source_name() -> None:
    param = mcp_tool_to_function_param(
        {"name": "Read File!", "inputSchema": {"type": "object"}},
        server_label="demo",
    )

    assert param["name"] == "mcp.demo.read_file"
    assert param["x_anyagent_source_name"] == "Read File!"


def test_function_tool_param_accepts_mcp_source_name() -> None:
    param = mcp_tool_to_function_param(
        {
            "name": "maps_regeocode",
            "description": "Reverse geocode",
            "inputSchema": {"type": "object", "properties": {}},
        },
        server_label="amap-maps",
    )

    tool = AnyAgentFunctionToolParam.model_validate(param)
    assert tool.name == "mcp.amap-maps.maps_regeocode"
    assert tool.x_anyagent_kind == "mcp"
    assert tool.x_anyagent_source_name == "maps_regeocode"

    hyphenated = dict(param)
    hyphenated.pop("x_anyagent_source_name")
    hyphenated["x-anyagent-source-name"] = "maps_regeocode"
    assert AnyAgentFunctionToolParam.model_validate(hyphenated).x_anyagent_source_name == "maps_regeocode"


def test_manager_calls_raw_source_tool_name_after_sanitize() -> None:
    async def _run() -> None:
        fake_server = _FakeMCPServer()
        manager = MCPServerManager(
            agent_id="main",
            mcp_config=MCPConfig.model_validate({"mcpServers": {"demo": {"url": "https://example.com/mcp"}}}),
        )
        manager._servers = {"demo": fake_server}  # type: ignore[assignment]

        tools = await manager.list_all_tools()
        result = await manager.call_tool("mcp.demo.read_file", {})

        assert tools[0]["name"] == "mcp.demo.read_file"
        assert fake_server.called_names == ["Read File!"]
        assert result == "Read File!"

    asyncio.run(_run())


def test_tool_filter_can_match_raw_or_sanitized_names() -> None:
    tools = [{"name": "Read File!"}, {"name": "Delete File!"}]
    server = _FilterServer(
        name="demo",
        agent_id="main",
        config=MCPServerConfig.model_validate(
            {
                "url": "https://example.com/mcp",
                "tool_filter": {"allowed_tool_names": ["read_file"], "match_mode": "sanitized"},
            }
        ),
    )

    assert [tool["name"] for tool in server._apply_tool_filter(tools)] == ["Read File!"]

    server.config.tool_filter = server.config.tool_filter.model_copy(
        update={"blocked_tool_names": ["Delete File!"], "match_mode": "both"}
    )

    assert [tool["name"] for tool in server._apply_tool_filter(tools)] == ["Read File!"]
