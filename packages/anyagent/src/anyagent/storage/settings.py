from __future__ import annotations

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    """
    Storage settings for anyagent (v0 target: Postgres+Redis).

    Notes:
    - Keep fields optional until storage is actually wired into runtime paths.
    - Env var names are frozen as part of req-3-1 / todo/storage.md.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    postgres_dsn: PostgresDsn | None = Field(default=None, alias="POSTGRES_DSN")
    redis_dsn: RedisDsn | None = Field(default=None, alias="REDIS_DSN")

    # Namespacing to avoid cross-app collisions when sharing a Redis instance.
    redis_namespace: str = Field(default="anyagent", alias="REDIS_NAMESPACE")

    # Postgres schema for logical isolation (v0 default: public).
    postgres_schema: str = Field(default="public", alias="POSTGRES_SCHEMA")

