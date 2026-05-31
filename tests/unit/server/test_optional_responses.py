from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from anyagent.protocol.openai_responses import build_minimal_openai_response_json
from anyagent.server.handlers.http_errors import (
    cancelled_response_error_json,
    optional_response_payload_from_run,
    optional_response_status_from_run,
)
from anyagent.server.routes.responses_optional_router import create_optional_responses_router
from anyagent.storage import stream_external_response_blocks
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


def test_optional_response_status_from_run_prefers_effective_status() -> None:
    run = SimpleNamespace(status="aborted", effective_status="cancelled", error_json=None)
    assert optional_response_status_from_run(run) == "cancelled"


def test_optional_response_status_from_run_maps_cancelled_error_json() -> None:
    run = SimpleNamespace(status="errored", effective_status=None, error_json={"code": "response_cancelled"})
    assert optional_response_status_from_run(run) == "cancelled"


def test_optional_response_payload_from_run_returns_final_response_when_openai_compatible() -> None:
    final = build_minimal_openai_response_json(response_id="resp_1", status="completed")
    run = SimpleNamespace(response_id="resp_1", status="completed", effective_status="completed", final_response_json=final)
    assert optional_response_payload_from_run(run) == final


def test_optional_response_payload_from_run_builds_minimal_response_with_created_at_ms() -> None:
    run = SimpleNamespace(
        response_id="resp_2",
        status="started",
        effective_status="in_progress",
        final_response_json=None,
        created_at_ms=123000,
        error_json=None,
    )
    payload = optional_response_payload_from_run(run)
    assert payload["id"] == "resp_2"
    assert payload["status"] == "in_progress"
    assert int(payload["created_at"]) == 123


def test_cancelled_response_error_json_is_stable() -> None:
    assert cancelled_response_error_json() == {
        "type": "cancelled",
        "message": "response cancelled by client request",
        "code": "response_cancelled",
    }


def test_optional_responses_router_retrieves_and_cancels_run() -> None:
    run_store = InMemoryRunStore()
    event_store = InMemoryEventStore()
    runtime = StorageRuntime(
        mode="none",
        run_store=run_store,
        event_store=event_store,
        lease_lock=InMemoryLeaseLock(),
        session_store=InMemorySessionStore(),
    )
    asyncio.run(
        run_store.try_create_started(
            response_id="resp_router_1",
            session_partition_key="main::router",
            idempotency_key="idem_router_1",
            stream=False,
        )
    )

    app = FastAPI()
    app.state.storage = runtime
    app.include_router(create_optional_responses_router(api_key="test-key"))

    with TestClient(app) as client:
        headers = {"authorization": "Bearer test-key"}
        started = client.get("/v1/responses/resp_router_1", headers=headers)
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "in_progress"

        cancelled = client.post("/v1/responses/resp_router_1/cancel", headers=headers)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

        repeated = client.post("/v1/responses/resp_router_1/cancel", headers=headers)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["status"] == "cancelled"

    events = event_store._events["resp_router_1"]
    assert [item.event for item in events] == ["response.completed", None]
    assert events[-1].data == "[DONE]"


def test_shared_storage_runtime_replays_and_cancels_across_nodes() -> None:
    run_store = InMemoryRunStore()
    event_store = InMemoryEventStore()
    lock = InMemoryLeaseLock()
    node_a = StorageRuntime(
        mode="external",
        run_store=run_store,
        event_store=event_store,
        lease_lock=lock,
        session_store=InMemorySessionStore(),
    )
    node_b = StorageRuntime(
        mode="external",
        run_store=run_store,
        event_store=event_store,
        lease_lock=lock,
        session_store=InMemorySessionStore(),
    )

    async def _seed_and_replay() -> list[bytes]:
        await node_a.run_store.try_create_started(
            response_id="resp_cross_node_1",
            session_partition_key="main::cross-node",
            idempotency_key="idem_cross_node_1",
            stream=True,
        )
        await node_a.event_store.append(
            response_id="resp_cross_node_1",
            session_partition_key="main::cross-node",
            event="response.created",
            data='{"response":{"id":"resp_cross_node_1","status":"in_progress"}}',
        )
        await node_a.event_store.append(
            response_id="resp_cross_node_1",
            session_partition_key="main::cross-node",
            event="response.output_text.delta",
            data='{"delta":"hi"}',
        )
        out: list[bytes] = []
        async for chunk in stream_external_response_blocks(
            run_store=node_b.run_store,
            event_store=node_b.event_store,
            response_id="resp_cross_node_1",
            last_seq=1,
            poll_timeout_s=0.01,
        ):
            out.append(chunk)
            break
        return out

    replayed = asyncio.run(_seed_and_replay())
    assert b"response.output_text.delta" in replayed[0]
    assert b'{"delta":"hi"}' in replayed[0]

    app = FastAPI()
    app.state.storage = node_b
    app.include_router(create_optional_responses_router(api_key="test-key"))

    with TestClient(app) as client:
        cancelled = client.post(
            "/v1/responses/resp_cross_node_1/cancel",
            headers={"authorization": "Bearer test-key"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

    cancelled_run = asyncio.run(node_a.run_store.get("resp_cross_node_1"))
    assert cancelled_run is not None
    assert cancelled_run.status == "errored"
    assert cancelled_run.error_json == cancelled_response_error_json()
