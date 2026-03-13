from __future__ import annotations

from typing import Any


def build_storage_capability_matrix(
    *,
    event_store: Any,
    run_store: Any,
    session_store: Any,
    session_lock_service: Any,
) -> dict[str, dict[str, Any]]:
    return {
        "event_store": _event_store_capabilities(event_store),
        "run_store": _run_store_capabilities(run_store),
        "session_store": _session_store_capabilities(session_store),
        "session_lock": _session_lock_capabilities(session_lock_service),
    }


def _base_capabilities(component: Any) -> dict[str, Any]:
    tokens = _runtime_tokens(component)
    uses_postgres = any("Postgres" in token for token in tokens)
    uses_redis = any("Redis" in token for token in tokens)
    uses_external = any("External" in token for token in tokens)
    tier = "reference"
    owner = "anyagent"
    if uses_postgres or uses_redis or uses_external or any("Cached" in token for token in tokens):
        tier = "external"
        owner = "anyagent-apps"

    if uses_postgres and uses_redis:
        source_of_truth = "postgres+redis"
    elif uses_postgres:
        source_of_truth = "postgres"
    elif uses_redis:
        source_of_truth = "redis"
    elif uses_external:
        source_of_truth = "external_service"
    else:
        source_of_truth = "process_memory"

    requires_services: list[str] = []
    if uses_postgres:
        requires_services.append("postgres")
    if uses_redis:
        requires_services.append("redis")
    if uses_external and "external_service" not in requires_services:
        requires_services.append("external_service")

    return {
        "tier": tier,
        "long_term_owner": owner,
        "source_of_truth": source_of_truth,
        "requires_services": requires_services,
        "restart_recovery": source_of_truth != "process_memory",
        "cross_instance": tier == "external",
    }


def _event_store_capabilities(component: Any) -> dict[str, Any]:
    out = _base_capabilities(component)
    out["supports_replay"] = True
    out["supports_live_tail"] = True
    return out


def _run_store_capabilities(component: Any) -> dict[str, Any]:
    out = _base_capabilities(component)
    out["supports_idempotency"] = True
    return out


def _session_store_capabilities(component: Any) -> dict[str, Any]:
    out = _base_capabilities(component)
    out["supports_snapshot_cas"] = True
    return out


def _session_lock_capabilities(component: Any) -> dict[str, Any]:
    out = _base_capabilities(component)
    out["supports_keyed_serialization"] = True
    return out


def _runtime_tokens(component: Any) -> set[str]:
    tokens = {component.__class__.__name__}
    for attr in ("_primary", "_cache", "_client"):
        value = getattr(component, attr, None)
        if value is not None:
            tokens.add(value.__class__.__name__)
    return tokens
