from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PluginCapability(BaseModel):
    """Describes one plugin capability surface exposed by a host."""

    capability: Literal[
        "channels",
        "webhook_routes",
        "skills",
        "mcp_servers",
        "tools",
        "middlewares",
        "hooks",
    ]
    host: Literal["gateway", "tool_runtime"]
    status: Literal["stable", "preview", "planned"] = "stable"
    description: str
    manifest_field: str | None = None
    registration_api: str | None = None
    source: str


class PluginCapabilityMatrix(BaseModel):
    """Lists the plugin manifest capabilities supported by each host."""

    manifest_schema: str
    manifest_version: str = "1"
    capabilities: list[PluginCapability] = Field(default_factory=list)
