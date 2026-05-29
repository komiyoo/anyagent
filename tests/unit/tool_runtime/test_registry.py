from __future__ import annotations

from typing import Any

from anyagent.tool_runtime.models import ToolDefinition, ToolExposure
from anyagent.tool_runtime.registry import ToolRegistry


async def _handler(args: dict[str, Any], context: dict[str, Any]) -> str:
    _ = args, context
    return "ok"


def _tool(name: str, *, exposure: ToolExposure = "direct") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} description",
        category="core" if name.startswith("core.") else "app",
        exposure=exposure,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "required": [],
            "properties": {},
        },
    )


def test_registry_lists_direct_tools_and_searches_deferred_tools_only() -> None:
    registry = ToolRegistry()
    registry.register_tool(_tool("core.visible"), _handler)
    registry.register_tool(_tool("core.fetch_url", exposure="deferred"), _handler)
    registry.register_tool(_tool("core.secret_admin", exposure="hidden"), _handler)

    assert [tool.name for tool in registry.list_tools()] == ["core.visible"]
    assert [tool.name for tool in registry.list_all_tools()] == [
        "core.fetch_url",
        "core.secret_admin",
        "core.visible",
    ]
    assert [tool.name for tool in registry.search_tools("fetch")] == ["core.fetch_url"]
    assert registry.search_tools("secret") == []
