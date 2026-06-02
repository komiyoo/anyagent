from __future__ import annotations

import os

from anyagent.server.persistence.events import PostgresEventStore
from anyagent.server.persistence.run_store import PostgresRunStore
from anyagent.server.persistence.session_store import PostgresSessionStore
from anyagent.server.persistence.storage_backends import build_server_storage_bundle
from anyagent.storage.external import MySQLEventStore, MySQLRunStore, MySQLSessionStore


def test_build_server_storage_bundle_prefers_postgres_by_default_when_both_sql_backends_exist() -> None:
    old = {key: os.environ.get(key) for key in ("POSTGRES_DSN", "MYSQL_DSN", "REDIS_DSN", "SQL_BACKEND_DIALECT")}
    os.environ["POSTGRES_DSN"] = "postgresql://user:pass@127.0.0.1:5432/anyagent"
    os.environ["MYSQL_DSN"] = "mysql+asyncmy://user:pass@127.0.0.1:3306/anyagent"
    os.environ["REDIS_DSN"] = "redis://127.0.0.1:6379/0"
    os.environ.pop("SQL_BACKEND_DIALECT", None)
    try:
        bundle = build_server_storage_bundle(
            event_store_backend="external",
            run_store_backend="external",
            session_store_backend="external",
        )
        assert bundle.event_store.__class__.__name__ != "MySQLEventStore"
        assert bundle.run_store.__class__.__name__ != "MySQLRunStore"
        assert bundle.session_store.__class__.__name__ != "MySQLSessionStore"
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_build_server_storage_bundle_external_postgres_only_does_not_require_redis() -> None:
    old = {key: os.environ.get(key) for key in ("POSTGRES_DSN", "DATABASE_URL", "MYSQL_DSN", "REDIS_DSN", "SQL_BACKEND_DIALECT")}
    os.environ["POSTGRES_DSN"] = "postgresql://user:pass@127.0.0.1:5432/anyagent"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("MYSQL_DSN", None)
    os.environ.pop("REDIS_DSN", None)
    os.environ.pop("SQL_BACKEND_DIALECT", None)
    try:
        bundle = build_server_storage_bundle(
            event_store_backend="external",
            run_store_backend="external",
            session_store_backend="external",
        )
        assert isinstance(bundle.event_store, PostgresEventStore)
        assert isinstance(bundle.run_store, PostgresRunStore)
        assert isinstance(bundle.session_store, PostgresSessionStore)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_build_server_storage_bundle_database_url_only_uses_postgres() -> None:
    old = {key: os.environ.get(key) for key in ("POSTGRES_DSN", "DATABASE_URL", "MYSQL_DSN", "REDIS_DSN", "SQL_BACKEND_DIALECT")}
    os.environ.pop("POSTGRES_DSN", None)
    os.environ["DATABASE_URL"] = "postgresql://user:pass@127.0.0.1:5432/anyagent"
    os.environ.pop("MYSQL_DSN", None)
    os.environ.pop("REDIS_DSN", None)
    os.environ.pop("SQL_BACKEND_DIALECT", None)
    try:
        bundle = build_server_storage_bundle(
            event_store_backend="postgres",
            run_store_backend="postgres",
            session_store_backend="postgres",
        )
        assert isinstance(bundle.event_store, PostgresEventStore)
        assert isinstance(bundle.run_store, PostgresRunStore)
        assert isinstance(bundle.session_store, PostgresSessionStore)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_build_server_storage_bundle_uses_mysql_when_explicitly_selected() -> None:
    old = {key: os.environ.get(key) for key in ("POSTGRES_DSN", "MYSQL_DSN", "REDIS_DSN", "SQL_BACKEND_DIALECT")}
    os.environ["POSTGRES_DSN"] = "postgresql://user:pass@127.0.0.1:5432/anyagent"
    os.environ["MYSQL_DSN"] = "mysql+asyncmy://user:pass@127.0.0.1:3306/anyagent"
    os.environ["REDIS_DSN"] = "redis://127.0.0.1:6379/0"
    os.environ["SQL_BACKEND_DIALECT"] = "mysql"
    try:
        bundle = build_server_storage_bundle(
            event_store_backend="external",
            run_store_backend="external",
            session_store_backend="external",
        )
        assert bundle.event_store.__class__.__name__ == "_ExternalSqlEventStoreAdapter"
        assert bundle.run_store.__class__.__name__ == "_ExternalSqlRunStoreAdapter"
        assert bundle.session_store.__class__.__name__ == "_ExternalSqlSessionStoreAdapter"
        assert isinstance(bundle.event_store._store, MySQLEventStore)
        assert isinstance(bundle.run_store._store, MySQLRunStore)
        assert isinstance(bundle.session_store._store, MySQLSessionStore)
        assert len(bundle.resources) == 1
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
