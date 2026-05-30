from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from anyagent.protocol.mcp import MCPServerConfig

from .hooks import HOOK_NAMES

_CLASSPATH_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


class PluginManifest(BaseModel):
    """
    Plugin manifest (`plugin.json`).

    v0 字段:
    - plugin_id：稳定标识（建议与目录名一致）
    - channels：支持的平台集合（feishu/discord/telegram/...）
    - config_schema：插件配置的 JSON Schema（可选）
    - entrypoint：相对插件目录的入口（可选），形如 "plugin.py:register"
    - docs / schemas / tests：可追溯资料的相对路径或稳定 URL（可选）

    v1 声明字段（一个 plugin 可同时声明多类能力）：
    - skills：相对插件目录的 skill 目录路径（每个目录含 SKILL.md）
    - mcp_servers：MCP server 配置（结构对齐 `mcp.json` 的 `mcpServers`）
    - tools：plugin 通过 register(api) 注册的 tool 名（声明 vs 实际注册可对账）
    - middlewares：Agent Loop middleware 类路径列表（"module.path:ClassName"）
    - hooks：生命周期回调类路径（on_agent_start / on_agent_end → "module.path:callable"）
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    manifest_version: Literal["1"] = Field(default="1", description="Plugin manifest contract version.")
    plugin_id: str = Field(min_length=1, max_length=64, validation_alias=AliasChoices("plugin_id", "id"))
    description: str | None = None
    channels: list[str] = Field(default_factory=list)
    config_schema: dict[str, Any] | None = None
    entrypoint: str | None = None
    docs: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)

    skills: list[str] = Field(default_factory=list)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    middlewares: list[str] = Field(default_factory=list)
    hooks: dict[str, str] = Field(default_factory=dict)

    @field_validator("middlewares")
    @classmethod
    def _validate_middleware_classpaths(cls, value: list[str]) -> list[str]:
        for item in value:
            if not isinstance(item, str) or not _CLASSPATH_RE.match(item.strip()):
                raise ValueError(f"invalid middleware classpath (expected 'module.path:ClassName'): {item!r}")
        return [item.strip() for item in value]

    @field_validator("hooks")
    @classmethod
    def _validate_hooks(cls, value: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for name, classpath in value.items():
            if name not in HOOK_NAMES:
                raise ValueError(f"unknown hook name: {name!r} (allowed: {list(HOOK_NAMES)})")
            if not isinstance(classpath, str) or not _CLASSPATH_RE.match(classpath.strip()):
                raise ValueError(f"invalid hook classpath for {name!r} (expected 'module.path:callable'): {classpath!r}")
            out[name] = classpath.strip()
        return out
