from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, PostgresDsn, RedisDsn, UrlConstraints
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

MySQLDsn = Annotated[AnyUrl, UrlConstraints(allowed_schemes=["mysql", "mysql+asyncmy", "mysql+aiomysql", "mysql+pymysql"])]
SqlBackendDialect = Literal["postgresql", "mysql"]


class ExternalSqlBackendConfig(BaseModel):
    """Typed contract for one SQL backend slot used by storage adapters."""

    model_config = ConfigDict(extra="forbid")

    dialect: SqlBackendDialect
    postgres_dsn: PostgresDsn | None = None
    mysql_dsn: MySQLDsn | None = None
    redis_dsn: RedisDsn | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    namespace: str | None = Field(default=None)

    @property
    def sql_dsn(self) -> str:
        if self.dialect == "postgresql" and self.postgres_dsn is not None:
            return str(self.postgres_dsn)
        if self.dialect == "mysql" and self.mysql_dsn is not None:
            return str(self.mysql_dsn)
        raise RuntimeError(f"missing sql dsn for dialect={self.dialect}")


def resolve_external_sql_backend_config(
    *,
    postgres_dsn: PostgresDsn | None,
    mysql_dsn: MySQLDsn | None,
    redis_dsn: RedisDsn | None,
    schema_name: str | None,
    namespace: str | None,
    dialect: Literal["auto", "postgresql", "mysql"] = "auto",
) -> ExternalSqlBackendConfig:
    chosen = dialect
    if chosen == "auto":
        has_pg = postgres_dsn is not None
        has_mysql = mysql_dsn is not None
        if has_pg and has_mysql:
            raise RuntimeError("ambiguous SQL backend: set SQL_BACKEND_DIALECT when both POSTGRES_DSN and MYSQL_DSN are configured")
        if has_pg:
            chosen = "postgresql"
        elif has_mysql:
            chosen = "mysql"
        else:
            raise RuntimeError("external SQL backend requires POSTGRES_DSN or MYSQL_DSN")

    config = ExternalSqlBackendConfig(
        dialect=chosen,
        postgres_dsn=postgres_dsn,
        mysql_dsn=mysql_dsn,
        redis_dsn=redis_dsn,
        schema=schema_name if chosen == "postgresql" else None,
        namespace=namespace,
    )
    _validate_external_sql_backend_config(config)
    return config


def create_external_sql_engine(config: ExternalSqlBackendConfig) -> AsyncEngine:
    return create_async_engine(
        _normalize_async_sql_dsn(config),
        pool_pre_ping=True,
        future=True,
    )


def _validate_external_sql_backend_config(config: ExternalSqlBackendConfig) -> None:
    if config.dialect == "postgresql" and config.postgres_dsn is None:
        raise RuntimeError("dialect=postgresql requires POSTGRES_DSN")
    if config.dialect == "mysql" and config.mysql_dsn is None:
        raise RuntimeError("dialect=mysql requires MYSQL_DSN")


def _normalize_async_sql_dsn(config: ExternalSqlBackendConfig) -> str:
    dsn = config.sql_dsn
    if config.dialect == "postgresql" and dsn.startswith("postgresql://"):
        return "postgresql+psycopg://" + dsn[len("postgresql://") :]
    if config.dialect == "mysql" and dsn.startswith("mysql://"):
        return "mysql+asyncmy://" + dsn[len("mysql://") :]
    return dsn
