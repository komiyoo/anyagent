from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8788, alias="PORT")

    tool_runtime_internal_key: str = Field(alias="TOOL_RUNTIME_INTERNAL_KEY")
    admin_api_key: str | None = Field(default=None, alias="ADMIN_API_KEY")

    allow_sandbox: bool = Field(default=False, alias="ALLOW_SANDBOX")
    sandbox_isolation_mode: str = Field(default="disabled", alias="SANDBOX_ISOLATION_MODE")

    output_max_bytes: int = Field(default=64 * 1024, alias="TOOL_OUTPUT_MAX_BYTES")

    # Credential Store（req-8）：v1 默认 env（仅 resolve；set/delete/list 主要供后续 Admin API/CLI 使用）。
    credential_store_backend: str = Field(default="env", alias="CREDENTIAL_STORE_BACKEND")
    credential_store_file_root: str = Field(default="/data/credentials", alias="CREDENTIAL_STORE_FILE_ROOT")

    # 插件化（req-6-1）：目录列表（逗号分隔），每个 root 下任意包含 plugin.json 的目录视为插件目录。
    plugin_roots: str = Field(default="", alias="TOOL_RUNTIME_PLUGIN_ROOTS")
    plugins_fail_open: bool = Field(default=False, alias="TOOL_RUNTIME_PLUGINS_FAIL_OPEN")
