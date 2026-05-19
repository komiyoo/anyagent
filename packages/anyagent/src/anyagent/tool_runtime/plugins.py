from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from anyagent.plugins.api import PluginAPIBase

from .models import ToolDefinition, ToolHandler
from .registry import RESERVED_NAMES, ToolRegistry


class ToolRuntimePluginError(Exception):
    pass


@dataclass(frozen=True)
class ToolRuntimePluginAPI(PluginAPIBase):
    registry: ToolRegistry
    registered_tools: list[ToolDefinition] | None = None

    def registerTool(  # noqa: N802
        self,
        tool_or_factory: ToolDefinition | Callable[[], tuple[ToolDefinition, ToolHandler]],
        handler: ToolHandler | None = None,
    ) -> None:
        tool: ToolDefinition
        h: ToolHandler

        if callable(tool_or_factory) and handler is None:
            out = tool_or_factory()
            if not isinstance(out, tuple) or len(out) != 2:
                raise ToolRuntimePluginError("tool factory must return (ToolDefinition, ToolHandler)")
            tool, h = out
        else:
            if handler is None:
                raise ToolRuntimePluginError("handler is required when registering a ToolDefinition")
            tool = tool_or_factory  # type: ignore[assignment]
            h = handler

        if not isinstance(tool, ToolDefinition):
            raise ToolRuntimePluginError("tool must be a ToolDefinition")

        forbidden_prefixes = ("core.", "sandbox.", "admin.")
        if tool.name in RESERVED_NAMES or tool.name.startswith(forbidden_prefixes):
            raise ToolRuntimePluginError(
                "plugin cannot register privileged tool names (core./sandbox./admin. or reserved); "
                f"got: {tool.name}"
            )

        self.registry.register_tool(tool, h)
        if self.registered_tools is not None:
            self.registered_tools.append(tool)
