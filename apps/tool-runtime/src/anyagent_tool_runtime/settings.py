from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8788, alias="PORT")

    tool_runtime_internal_key: str = Field(alias="TOOL_RUNTIME_INTERNAL_KEY")

    allow_sandbox: bool = Field(default=False, alias="ALLOW_SANDBOX")

    output_max_bytes: int = Field(default=64 * 1024, alias="TOOL_OUTPUT_MAX_BYTES")

    # 插件化（req-6-1）：目录列表（逗号分隔），每个 root 下任意包含 plugin.json 的目录视为插件目录。
    plugin_roots: str = Field(default="", alias="TOOL_RUNTIME_PLUGIN_ROOTS")
    plugins_fail_open: bool = Field(default=False, alias="TOOL_RUNTIME_PLUGINS_FAIL_OPEN")
