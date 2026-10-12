from __future__ import annotations

import os
from typing import Annotated, Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, PostgresDsn, RedisDsn, UrlConstraints

from anyagent.config.schema import StorageConfig


MySQLDsn = Annotated[AnyUrl, UrlConstraints(allowed_schemes=["mysql", "mysql+asyncmy", "mysql+aiomysql", "mysql+pymysql"])]


class StorageSettings(BaseModel):
    """Resolved storage settings.

    Construct this from ``StorageConfig`` or pass explicit values. A no-arg
    constructor does not read the environment; call ``active_storage_settings``
    for the process configuration.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    postgres_dsn: PostgresDsn | None = Field(default=None, alias="POSTGRES_DSN")
    database_url: PostgresDsn | None = Field(default=None, alias="DATABASE_URL")
    mysql_dsn: MySQLDsn | None = Field(default=None, alias="MYSQL_DSN")
    redis_dsn: RedisDsn | None = Field(default=None, alias="REDIS_DSN")
    sql_backend_dialect: Literal["auto", "postgresql", "mysql"] = Field(default="auto", alias="SQL_BACKEND_DIALECT")

    redis_namespace: str = Field(default="anyagent", alias="REDIS_NAMESPACE")
    event_store_retention_s: int = Field(default=2 * 60 * 60, alias="EVENT_STORE_RETENTION_S")
    replay_event_store_retention_s: int = Field(default=60 * 60, alias="REPLAY_EVENT_STORE_RETENTION_S")
    run_store_retention_s: int = Field(default=2 * 60 * 60, alias="RUN_STORE_RETENTION_S")
    session_store_retention_s: int = Field(default=24 * 60 * 60, alias="SESSION_STORE_RETENTION_S")

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


def storage_settings_from_config(storage: StorageConfig) -> StorageSettings:
    """Build storage settings from the effective config section.

    ``postgres_dsn`` already includes the DATABASE_URL fallback, so
    ``database_url`` stays unset here.
    """

    return StorageSettings(
        postgres_dsn=storage.postgres_dsn,
        mysql_dsn=storage.mysql_dsn,
        redis_dsn=storage.redis_dsn,
        sql_backend_dialect=storage.sql_backend_dialect,
        redis_namespace=storage.redis_namespace,
        event_store_retention_s=storage.event_store_retention_s,
        replay_event_store_retention_s=storage.replay_event_store_retention_s,
        run_store_retention_s=storage.run_store_retention_s,
        session_store_retention_s=storage.session_store_retention_s,
        postgres_schema=storage.postgres_schema,
        postgres_schema_policy=storage.postgres_schema_policy,
        storage_mode=storage.mode or "auto",
        rollout_root_dir=storage.rollout_root_dir,
        rollout_rotate_max_bytes=storage.rollout_rotate_max_bytes,
        rollout_rotate_max_age_seconds=storage.rollout_rotate_max_age_seconds,
        rollout_rotate_keep_files=storage.rollout_rotate_keep_files,
    )


def active_storage_settings() -> StorageSettings:
    """Load storage settings from the current workspace configuration.

    ``WORKSPACE_DIR`` selects the workspace. Otherwise the current directory
    is used. This reads the environment through ``load_effective_config`` and
    does not cache the result.
    """

    from anyagent.config.loader import load_effective_config

    workspace = os.environ.get("WORKSPACE_DIR") or "."
    return storage_settings_from_config(load_effective_config(workspace).storage)
