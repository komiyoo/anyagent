from __future__ import annotations

__all__ = [
    "ExternalSqlBackendConfig",
    "MySQLDsn",
    "MySQLEventStore",
    "MySQLRunStore",
    "MySQLSessionStore",
    "PostgresEventStore",
    "PostgresLeaseLock",
    "PostgresRunStore",
    "PostgresSessionStore",
    "RedisLeaseLock",
    "SqlBackendDialect",
    "apply_external_storage_schema",
    "apply_external_storage_schema_async",
    "create_external_sql_engine",
    "default_postgres_migrations_dir",
    "resolve_external_sql_backend_config",
]

_CONFIG_EXPORTS = {
    "ExternalSqlBackendConfig",
    "MySQLDsn",
    "SqlBackendDialect",
    "create_external_sql_engine",
    "resolve_external_sql_backend_config",
}
_MYSQL_EXPORTS = {"MySQLEventStore", "MySQLRunStore", "MySQLSessionStore"}
_POSTGRES_EXPORTS = {"PostgresEventStore", "PostgresLeaseLock", "PostgresRunStore", "PostgresSessionStore"}
_MIGRATION_EXPORTS = {
    "apply_external_storage_schema",
    "apply_external_storage_schema_async",
    "default_postgres_migrations_dir",
}
_REDIS_EXPORTS = {"RedisLeaseLock"}


def __getattr__(name: str):
    if name in _CONFIG_EXPORTS:
        from . import config

        return getattr(config, name)
    if name in _MYSQL_EXPORTS:
        from . import mysql

        return getattr(mysql, name)
    if name in _POSTGRES_EXPORTS:
        from . import postgres

        return getattr(postgres, name)
    if name in _MIGRATION_EXPORTS:
        from . import migrations

        return getattr(migrations, name)
    if name in _REDIS_EXPORTS:
        from . import redis_lock

        return getattr(redis_lock, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
