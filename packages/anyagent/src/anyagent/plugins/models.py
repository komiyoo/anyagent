from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class PluginManifest(BaseModel):
    """
    v0 约定：插件目录下的 plugin.json（最小字段）：
    - plugin_id：稳定标识（建议与目录名一致）
    - channels：支持的平台集合（feishu/discord/telegram/...）
    - config_schema：插件配置的 JSON Schema（可选）
    - entrypoint：相对插件目录的入口（可选），形如 "plugin.py:register"
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    plugin_id: str = Field(min_length=1, max_length=64, validation_alias=AliasChoices("plugin_id", "id"))
    channels: list[str] = Field(default_factory=list)
    config_schema: dict[str, Any] | None = None
    entrypoint: str | None = None
