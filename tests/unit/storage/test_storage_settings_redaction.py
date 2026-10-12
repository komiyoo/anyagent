from __future__ import annotations

import pytest

from anyagent.server.persistence.storage_backends import build_server_storage_bundle
from anyagent.storage.settings import StorageSettings


def test_storage_settings_repr_redacts_dsn_passwords() -> None:
    settings = StorageSettings(
        postgres_dsn="postgresql://user:s3cret@host/db",
        redis_dsn="redis://:s3cret@redis:6379/0",
        database_url="postgresql://user:s3cret@fallback/db",
    )

    text = f"{settings!r} {settings}"
    assert "s3cret" not in text
    assert "postgresql://user:***@host/db" in text
    assert "redis://:***@redis:6379/0" in text
    assert str(settings.postgres_dsn) == "postgresql://user:s3cret@host/db"


def test_explicit_storage_settings_reach_every_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_DSN", raising=False)

    def _unexpected() -> StorageSettings:
        raise AssertionError("active_storage_settings should not reload the environment")

    monkeypatch.setattr("anyagent.server.persistence.storage_backends.active_storage_settings", _unexpected)
    settings = StorageSettings(
        postgres_dsn="postgresql://user:s3cret@db.example:5432/app",
        redis_dsn="redis://:s3cret@redis.example:6379/0",
        postgres_schema="custom",
        redis_namespace="ns",
    )

    bundle = build_server_storage_bundle(
        event_store_backend="postgres-redis",
        run_store_backend="postgres-redis",
        session_store_backend="postgres-redis",
        storage_settings=settings,
    )

    postgres_dsn = "postgresql://user:s3cret@db.example:5432/app"
    redis_dsn = "redis://:s3cret@redis.example:6379/0"
    assert bundle.event_store._primary._postgres_dsn == postgres_dsn
    assert bundle.event_store._primary._postgres_schema == "custom"
    assert bundle.event_store._cache._redis_dsn == redis_dsn
    assert bundle.event_store._cache._namespace == "ns"
    assert bundle.run_store._cache._redis_dsn == redis_dsn
    assert bundle.session_store._cache._redis_dsn == redis_dsn
    run_url = bundle.run_store._primary._engine.url.render_as_string(hide_password=False)
    session_url = bundle.session_store._primary._engine.url.render_as_string(hide_password=False)
    assert "db.example" in run_url
    assert "s3cret" in run_url
    assert "db.example" in session_url
    assert "s3cret" in session_url


def test_database_url_only_reaches_postgres_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def _unexpected() -> StorageSettings:
        raise AssertionError("active_storage_settings should not reload the environment")

    monkeypatch.setattr("anyagent.server.persistence.storage_backends.active_storage_settings", _unexpected)
    settings = StorageSettings(database_url="postgresql://user:s3cret@db.example:5432/app")
    bundle = build_server_storage_bundle(
        event_store_backend="postgres",
        run_store_backend="postgres",
        session_store_backend="postgres",
        storage_settings=settings,
    )

    dsn = "postgresql://user:s3cret@db.example:5432/app"
    assert bundle.event_store._postgres_dsn == dsn
    assert "s3cret" in bundle.run_store._engine.url.render_as_string(hide_password=False)
    assert "s3cret" in bundle.session_store._engine.url.render_as_string(hide_password=False)
