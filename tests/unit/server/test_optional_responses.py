from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from anyagent.protocol.openai_responses import build_minimal_openai_response_json
from anyagent.server.responses_optional import (
    cancelled_response_error_json,
    create_optional_responses_router,
    optional_response_payload_from_run,
    optional_response_status_from_run,
)
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
