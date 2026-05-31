from __future__ import annotations

from typing import Any

from anyagent.storage import build_storage_capability_matrix


async def _build_storage_health_payload(state: Any) -> dict[str, Any]:
    uses_postgres = (
        _uses_backend(state.events, "Postgres")
        or _uses_backend(state.run_store, "Postgres")
        or _uses_backend(state.session_store, "Postgres")
        or _uses_backend(state.telemetry_event_store, "Postgres")
    )
    uses_redis = (
        _uses_backend(state.events, "Redis")
        or _uses_backend(state.run_store, "Redis")
        or _uses_backend(state.session_store, "Redis")
        or _uses_backend(state.session_lock_service, "Redis")
        or _uses_backend(state.session_lock_service, "External")
    )

    postgres_status = await _check_postgres_connection(str(state.storage_settings.postgres_dsn)) if uses_postgres and state.storage_settings.postgres_dsn is not None else None
    redis_status = await _check_redis_connection(str(state.storage_settings.redis_dsn)) if uses_redis and state.storage_settings.redis_dsn is not None else None

    stores = {
        "events": _describe_runtime_component(state.events),
        "run_store": _describe_runtime_component(state.run_store),
        "session_store": _describe_runtime_component(state.session_store),
        "session_lock_service": _describe_runtime_component(state.session_lock_service),
        "telemetry_store": _describe_runtime_component(state.telemetry_store),
        "telemetry_events": _describe_runtime_component(state.telemetry_event_store),
    }
    ok = True
    if uses_postgres:
        ok = ok and bool(postgres_status)
    if uses_redis:
        ok = ok and bool(redis_status)

    return {
        "ok": ok,
        "storage_mode": state.resolved_storage.storage_mode,
        "backends": {
            "event_store": state.resolved_storage.event_store_backend,
            "run_store": state.resolved_storage.run_store_backend,
            "session_store": state.resolved_storage.session_store_backend,
            "session_lock": state.resolved_storage.session_lock_backend,
        },
        "retention_s": {
            "events": state.storage_settings.event_store_retention_s,
            "runs": state.storage_settings.run_store_retention_s,
            "sessions": state.storage_settings.session_store_retention_s,
        },
        "stores": stores,
        "capabilities": build_storage_capability_matrix(
            event_store=state.events,
            run_store=state.run_store,
            session_store=state.session_store,
            session_lock_service=state.session_lock_service,
            workspace_store=state.sandbox_manager.workspace_service,
        ),
        "postgres": {
            "configured": state.storage_settings.postgres_dsn is not None,
            "schema": state.storage_settings.postgres_schema,
            "schema_policy": state.storage_settings.postgres_schema_policy,
            "reachable": postgres_status,
        },
        "redis": {
            "configured": state.storage_settings.redis_dsn is not None,
            "namespace": state.storage_settings.redis_namespace,
            "reachable": redis_status,
        },
    }


def _describe_runtime_component(component: Any) -> dict[str, Any]:
    info = {"type": component.__class__.__name__}
    layers: list[str] = []
    for attr in ("_primary", "_cache", "_client"):
        value = getattr(component, attr, None)
        if value is not None:
            layers.append(value.__class__.__name__)
    if layers:
        info["layers"] = layers
    return info


def _uses_backend(component: Any, token: str) -> bool:
    if token in component.__class__.__name__:
        return True
    for attr in ("_primary", "_cache", "_client"):
        value = getattr(component, attr, None)
        if value is not None and token in value.__class__.__name__:
            return True
    return False


async def _check_postgres_connection(postgres_dsn: str) -> bool:
    try:
        from psycopg import AsyncConnection

        async with await AsyncConnection.connect(postgres_dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                row = await cur.fetchone()
        return bool(row and row[0] == 1)
    except Exception:
        return False


async def _check_redis_connection(redis_dsn: str) -> bool:
    try:
        from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]

        client = redis_asyncio.from_url(redis_dsn, encoding="utf-8", decode_responses=True)
        try:
            pong = await client.ping()
            return bool(pong)
        finally:
            await client.aclose()
    except Exception:
        return False
