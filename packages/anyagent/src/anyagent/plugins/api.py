from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, runtime_checkable

from anyagent.tool_runtime.models import ToolDefinition, ToolHandler


@runtime_checkable
class AnyAgentPluginAPI(Protocol):
    """
    v0 插件 Host API（跨进程契约）：
    - 同一份插件代码在不同宿主（Gateway / Tool Runtime）加载
    - 插件入口：register(api)
    - 插件根据 host_kind 选择注册哪些能力
    """

    host_kind: Literal["gateway", "tool_runtime"]
    plugin_id: str
    config: dict[str, Any]

    def registerChannel(self, connector: Any) -> None:  # noqa: N802
        ...

    def registerTool(  # noqa: N802
        self,
        tool_or_factory: ToolDefinition | Callable[[], tuple[ToolDefinition, ToolHandler]],
        handler: ToolHandler | None = None,
    ) -> None:
        ...

    def registerWebhookRoute(self, route: Any) -> None:  # noqa: N802
        ...


@dataclass(frozen=True)
class PluginAPIBase:
    host_kind: Literal["gateway", "tool_runtime"]
    plugin_id: str
    config: dict[str, Any]

    def registerChannel(self, connector: Any) -> None:  # noqa: N802
        raise NotImplementedError(f"registerChannel is not supported in host={self.host_kind}")

    def registerTool(  # noqa: N802
        self,
        tool_or_factory: ToolDefinition | Callable[[], tuple[ToolDefinition, ToolHandler]],
        handler: ToolHandler | None = None,
    ) -> None:
        raise NotImplementedError(f"registerTool is not supported in host={self.host_kind}")

    def registerWebhookRoute(self, route: Any) -> None:  # noqa: N802
        raise NotImplementedError(f"registerWebhookRoute is not supported in host={self.host_kind}")

