from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AnyUrl, Field, PostgresDsn, RedisDsn, UrlConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict


MySQLDsn = Annotated[AnyUrl, UrlConstraints(allowed_schemes=["mysql", "mysql+asyncmy", "mysql+aiomysql", "mysql+pymysql"])]


class StorageSettings(BaseSettings):
    """
    Storage settings for anyagent (v0 target: Postgres+Redis).

    Notes:
    - Keep fields optional until storage is actually wired into runtime paths.
    - Env var names are frozen as part of req-3-1 / docs/architecture/storage/storage-minimal-design.md.
    - DATABASE_URL is accepted as a fallback for POSTGRES_DSN (Infisical convention).
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    postgres_dsn: PostgresDsn | None = Field(default=None, alias="POSTGRES_DSN")
    database_url: PostgresDsn | None = Field(default=None, alias="DATABASE_URL")
    mysql_dsn: MySQLDsn | None = Field(default=None, alias="MYSQL_DSN")
    redis_dsn: RedisDsn | None = Field(default=None, alias="REDIS_DSN")
    sql_backend_dialect: Literal["auto", "postgresql", "mysql"] = Field(default="auto", alias="SQL_BACKEND_DIALECT")

    # Namespacing to avoid cross-app collisions when sharing a Redis instance.
    redis_namespace: str = Field(default="anyagent", alias="REDIS_NAMESPACE")
    event_store_retention_s: int = Field(default=2 * 60 * 60, alias="EVENT_STORE_RETENTION_S")
    run_store_retention_s: int = Field(default=2 * 60 * 60, alias="RUN_STORE_RETENTION_S")
    session_store_retention_s: int = Field(default=24 * 60 * 60, alias="SESSION_STORE_RETENTION_S")

    # Postgres schema for logical isolation (v0 default: public).
    postgres_schema: str = Field(default="public", alias="POSTGRES_SCHEMA")
    postgres_schema_policy: Literal["migrate", "runtime_create"] = Field(
        default="migrate",
        alias="POSTGRES_SCHEMA_POLICY",
    )

    storage_mode: Literal["auto", "none", "local", "external"] = Field(default="auto", alias="STORAGE_MODE")
    rollout_root_dir: str | None = Field(default=None, alias="ROLLOUT_ROOT_DIR")
    rollout_rotate_max_bytes: int = Field(default=0, alias="ROLLOUT_ROTATE_MAX_BYTES")
    rollout_rotate_max_age_seconds: int = Field(default=0, alias="ROLLOUT_ROTATE_MAX_AGE_SECONDS")
    rollout_rotate_keep_files: int = Field(default=16, alias="ROLLOUT_ROTATE_KEEP_FILES")

    @property
    def effective_postgres_dsn(self) -> PostgresDsn | None:
        """POSTGRES_DSN takes precedence; falls back to DATABASE_URL."""
        return self.postgres_dsn or self.database_url
