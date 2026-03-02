from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from anyagent.plugins.api import PluginAPIBase


class GatewayRegistrationError(Exception):
    pass


@dataclass(frozen=True)
class WebhookRoute:
    """
    框架无关的 webhook 路由描述（由 Gateway host 负责挂载到 FastAPI/Flask/...）。
    """

    path: str
    methods: tuple[str, ...] = ("POST",)
    handler: Callable[..., Any] = lambda *_args, **_kwargs: None  # noqa: E731


@dataclass
class GatewayRegistry:
    """
    v0 Gateway 注册表（单一真源）：
    - channel connector：按 channel key 去重
    - webhook routes：顺序保留（由 host 决定冲突策略/中间件）
    """

    channel_connectors: dict[str, Any] = field(default_factory=dict)
    webhook_routes: list[WebhookRoute] = field(default_factory=list)

    def register_channel(self, connector: Any) -> None:
        channel = getattr(connector, "channel", None)
        if not isinstance(channel, str) or not channel.strip():
            raise GatewayRegistrationError("connector must provide non-empty 'channel' attribute")
        channel = channel.strip()
        if channel in self.channel_connectors:
            raise GatewayRegistrationError(f"duplicate channel connector registration: {channel}")
        self.channel_connectors[channel] = connector

    def register_webhook_route(self, route: WebhookRoute) -> None:
        if not isinstance(route.path, str) or not route.path.startswith("/"):
            raise GatewayRegistrationError("webhook route.path must start with '/'")
        if not route.methods:
            raise GatewayRegistrationError("webhook route.methods must be non-empty")
        self.webhook_routes.append(route)


@dataclass(frozen=True)
class GatewayPluginAPI(PluginAPIBase):
    registry: GatewayRegistry

    def registerChannel(self, connector: Any) -> None:  # noqa: N802
        self.registry.register_channel(connector)

    def registerWebhookRoute(self, route: Any) -> None:  # noqa: N802
        if not isinstance(route, WebhookRoute):
            raise GatewayRegistrationError("route must be a WebhookRoute")
        self.registry.register_webhook_route(route)

