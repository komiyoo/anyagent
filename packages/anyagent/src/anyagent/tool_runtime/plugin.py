from __future__ import annotations

from dataclasses import dataclass

from .registry import ToolRegistry


@dataclass(frozen=True)
class ToolRuntimeSDK:
    """
    v0 最小 plugin host API（Tool Runtime 侧）。
    目前只暴露 registry；未来可扩展 namespace routes、health hooks 等。
    """

    registry: ToolRegistry


class ToolRuntimePlugin:
    """
    插件契约（同一份代码可以在不同宿主注册不同能力）：
    - Tool Runtime 侧：注册 <channel>.* 或 app.* tools
    """

    def register_tools(self, sdk: ToolRuntimeSDK) -> None:  # pragma: no cover
        raise NotImplementedError

