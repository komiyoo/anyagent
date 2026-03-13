from __future__ import annotations

"""Offline smoke for AnyAgent client sync/async entry semantics."""

import asyncio
from unittest.mock import patch

from anyagent import AnyAgent
from anyagent.agent_api_client import Admin, Responses
from anyagent.protocol.admin_storage import StorageHealthResponse
from anyagent.protocol.openai_responses import build_minimal_openai_response_json


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    """Validate cached OpenAI entrypoints and explicit factory semantics."""

    client = AnyAgent(api_key="test-key", base_url="http://127.0.0.1:8787/")

    sync_1 = client.openai
    sync_2 = client.openai
    _assert(sync_1 is sync_2, "`client.openai` should cache one sync SDK client")
    _assert(str(sync_1.base_url).rstrip("/") == "http://127.0.0.1:8787/v1", "sync base_url mismatch")

    async_1 = client.async_openai
    async_2 = client.async_openai
    _assert(async_1 is async_2, "`client.async_openai` should cache one async SDK client")
    _assert(str(async_1.base_url).rstrip("/") == "http://127.0.0.1:8787/v1", "async base_url mismatch")

    sync_new = client.as_openai_client()
    async_new = client.as_async_openai_client()
    _assert(sync_new is not sync_1, "`as_openai_client()` should return a fresh sync SDK client")
    _assert(async_new is not async_1, "`as_async_openai_client()` should return a fresh async SDK client")

    client_v1 = AnyAgent(api_key="test-key", base_url="http://127.0.0.1:8787/v1")
    _assert(
        str(client_v1.openai.base_url).rstrip("/") == "http://127.0.0.1:8787/v1",
        "pre-normalized /v1 base_url should not duplicate suffix",
    )

    async def _fake_retrieve_valid(self: Responses, response_id: str) -> dict:
        return build_minimal_openai_response_json(response_id=response_id, status="completed")

    async def _fake_retrieve_invalid(self: Responses, response_id: str) -> dict:
        return {"oops": response_id}

    with patch.object(Responses, "retrieve", _fake_retrieve_valid):
        typed = asyncio.run(client.responses.retrieve_typed("resp_typed_ok"))
        _assert(getattr(typed, "id", None) == "resp_typed_ok", "`retrieve_typed` should decode valid Response payload")

    with patch.object(Responses, "retrieve", _fake_retrieve_invalid):
        typed_none = asyncio.run(client.responses.retrieve_typed("resp_typed_bad"))
        _assert(typed_none is None, "`retrieve_typed` should return None for invalid payload")

    async def _fake_storage_health(self: Admin) -> StorageHealthResponse:
        return StorageHealthResponse.model_validate({
            "ok": True,
            "storage_mode": "external",
            "backends": {
                "event_store": "external",
                "run_store": "external",
                "session_store": "external",
                "session_lock": "redis",
            },
            "retention_s": {"events": 7200, "runs": 7200, "sessions": 86400},
            "stores": {"session_store": {"type": "CachedSessionStore", "layers": ["PostgresSessionStore", "RedisSessionStore"]}},
            "capabilities": {
                "session_store": {
                    "tier": "external",
                    "long_term_owner": "anyagent-apps",
                    "source_of_truth": "postgres+redis",
                    "requires_services": ["postgres", "redis"],
                    "restart_recovery": True,
                    "cross_instance": True,
                    "supports_snapshot_cas": True,
                }
            },
            "postgres": {"configured": True, "reachable": True, "schema": "public"},
            "redis": {"configured": True, "reachable": True, "namespace": "anyagent"},
        })

    with patch.object(Admin, "storage_health", _fake_storage_health):
        health = asyncio.run(client.admin.storage_health())
        _assert(health.ok is True, "`client.admin.storage_health()` should parse typed payload")
        _assert(health.backends.session_lock == "redis", "storage health backend parsing mismatch")
        _assert(health.capabilities["session_store"].tier == "external", "storage capability parsing mismatch")

    print("ok: acceptance_anyagent_client_surface_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
