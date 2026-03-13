from __future__ import annotations

from anyagent.storage import build_storage_capability_matrix
from anyagent.storage.external import ExternalSqlBackendConfig, resolve_external_sql_backend_config
from anyagent.server.events import InMemoryEventStore
from anyagent.server.lock_service import InMemorySessionLockService
from anyagent.server.run_store import InMemoryRunStore
from anyagent.server.session_store import InMemorySessionStore
from anyagent.server.storage_backends import build_event_store, build_run_store, build_session_store


def test_build_storage_capability_matrix_reports_reference_inmemory_components() -> None:
    matrix = build_storage_capability_matrix(
        event_store=InMemoryEventStore(),
        run_store=InMemoryRunStore(),
        session_store=InMemorySessionStore(),
        session_lock_service=InMemorySessionLockService(),
    )

    assert matrix["event_store"]["tier"] == "reference"
    assert matrix["event_store"]["long_term_owner"] == "anyagent"
    assert matrix["event_store"]["supports_replay"] is True
    assert matrix["run_store"]["supports_idempotency"] is True
    assert matrix["session_store"]["supports_snapshot_cas"] is True
    assert matrix["session_lock"]["supports_keyed_serialization"] is True


def test_build_storage_capability_matrix_reports_external_cached_components() -> None:
    import os

    old_postgres = os.environ.get("POSTGRES_DSN")
    old_redis = os.environ.get("REDIS_DSN")
    os.environ["POSTGRES_DSN"] = "postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent"
    os.environ["REDIS_DSN"] = "redis://127.0.0.1:6379/0"
    try:
        event_store = build_event_store(backend="external")
        run_store = build_run_store(backend="external")
        session_store = build_session_store(backend="external")

        class _ExternalLock:
            _client = object()

        matrix = build_storage_capability_matrix(
            event_store=event_store,
            run_store=run_store,
            session_store=session_store,
            session_lock_service=_ExternalLock(),
        )
    finally:
        if old_postgres is None:
            os.environ.pop("POSTGRES_DSN", None)
        else:
            os.environ["POSTGRES_DSN"] = old_postgres
        if old_redis is None:
            os.environ.pop("REDIS_DSN", None)
        else:
            os.environ["REDIS_DSN"] = old_redis

    assert matrix["event_store"]["tier"] == "external"
    assert matrix["event_store"]["long_term_owner"] == "anyagent-apps"
    assert matrix["event_store"]["source_of_truth"] == "postgres+redis"
    assert matrix["run_store"]["cross_instance"] is True
    assert matrix["session_store"]["restart_recovery"] is True


def test_external_sql_backend_config_accepts_mysql_dsn_contract() -> None:
    cfg = ExternalSqlBackendConfig.model_validate(
        {
            "dialect": "mysql",
            "mysql_dsn": "mysql+asyncmy://user:pass@127.0.0.1:3306/anyagent",
            "redis_dsn": "redis://127.0.0.1:6379/0",
            "schema": "public",
            "namespace": "anyagent",
        }
    )

    assert cfg.dialect == "mysql"
    assert str(cfg.mysql_dsn).startswith("mysql+asyncmy://")
    assert cfg.schema_name == "public"


def test_resolve_external_sql_backend_config_prefers_explicit_and_rejects_ambiguous_auto() -> None:
    cfg = resolve_external_sql_backend_config(
        postgres_dsn="postgresql://user:pass@127.0.0.1:5432/anyagent",
        mysql_dsn=None,
        redis_dsn="redis://127.0.0.1:6379/0",
        schema_name="public",
        namespace="anyagent",
        dialect="postgresql",
    )
    assert cfg.dialect == "postgresql"
    assert cfg.schema_name == "public"

    try:
        resolve_external_sql_backend_config(
            postgres_dsn="postgresql://user:pass@127.0.0.1:5432/anyagent",
            mysql_dsn="mysql+asyncmy://user:pass@127.0.0.1:3306/anyagent",
            redis_dsn="redis://127.0.0.1:6379/0",
            schema_name="public",
            namespace="anyagent",
            dialect="auto",
        )
    except RuntimeError as exc:
        assert "ambiguous SQL backend" in str(exc)
    else:
        raise AssertionError("expected ambiguous SQL backend error")
