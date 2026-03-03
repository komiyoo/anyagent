from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8787, alias="PORT")

    # 业务项目/工作区根目录（用于加载 `.agents/agents` 与 `.agents/skills`）
    workspace_dir: str = Field(default=".", alias="WORKSPACE_DIR")

    agent_api_key: str = Field(alias="AGENT_API_KEY")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    openai_base_url: AnyHttpUrl = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")

    tool_runtime_base_url: AnyHttpUrl = Field(default="http://127.0.0.1:8788", alias="TOOL_RUNTIME_BASE_URL")
    tool_runtime_internal_key: str = Field(alias="TOOL_RUNTIME_INTERNAL_KEY")

    enable_keyed_serialization: bool = Field(default=True, alias="ENABLE_KEYED_SERIALIZATION")

    manifest_cache_ttl_seconds: float = Field(default=5.0, alias="MANIFEST_CACHE_TTL_SECONDS")

    # Storage (v0 choice: Postgres+Redis). Optional until wired into runtime.
    storage_mode: Literal["auto", "none", "external"] = Field(default="auto", alias="STORAGE_MODE")
    postgres_dsn: PostgresDsn | None = Field(default=None, alias="POSTGRES_DSN")
    redis_dsn: RedisDsn | None = Field(default=None, alias="REDIS_DSN")
    redis_namespace: str = Field(default="anyagent", alias="REDIS_NAMESPACE")
    postgres_schema: str = Field(default="public", alias="POSTGRES_SCHEMA")
