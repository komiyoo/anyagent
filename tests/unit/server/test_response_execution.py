from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse

from anyagent.server.finalization import build_run_final_and_session_persister
from anyagent.server.response_execution import execute_distributed_nonstream_response, execute_distributed_stream_response
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


async def _noop_manifest() -> tuple[list[dict[str, Any]], int]:
    return [], 1


async def _noop_prompt_event(_response_id: str) -> None:
    return None


def test_execute_distributed_nonstream_response_advances_session_for_non_idempotent_success() -> None:
    asyncio.run(_run_execute_distributed_nonstream_response_advances_session_for_non_idempotent_success())


async def _run_execute_distributed_nonstream_response_advances_session_for_non_idempotent_success() -> None:
    advanced: list[dict[str, Any]] = []
    prompts: list[str] = []
    finals: list[dict[str, Any]] = []

    async def _run_loop(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        assert kwargs["idempotency_key"] is None
        assert kwargs["canonical_response_id"] == "resp_new"
        return 200, {"id": "resp_upstream", "object": "response", "status": "completed"}

    response = await execute_distributed_nonstream_response(
        model_provider=object(),
        tool_runtime=object(),
        agent_id="main",
        session_key="sess",
        body={"model": "gpt-test"},
        idempotency_key=None,
        idem_created=False,
        idem_response_id=None,
        tool_context=None,
        manifest_resolver=_noop_manifest,
        manifest_force_refresh=_noop_manifest,
        mcp_manager=None,
        stage_event_sink=None,
        append_prompt_context_event=lambda response_id: _record_prompt(prompts, response_id),
        finalize_nonstream_persisted=lambda **kwargs: _record(finals, kwargs),
        advance_nonstream_session_only=lambda **kwargs: _record(advanced, kwargs),
        new_response_id_factory=lambda: "resp_new",
        run_tool_loop_nonstream_fn=_run_loop,
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200
    assert json.loads(response.body)["id"] == "resp_upstream"
    assert prompts == []
    assert finals == []
    assert advanced == [
        {
            "run_response_id": "resp_upstream",
            "response_json": {"id": "resp_upstream", "object": "response", "status": "completed"},
            "effective_status": None,
            "resume_last_response_id": "resp_upstream",
        }
    ]


def test_execute_distributed_nonstream_response_finalizes_idempotent_success() -> None:
    asyncio.run(_run_execute_distributed_nonstream_response_finalizes_idempotent_success())


async def _run_execute_distributed_nonstream_response_finalizes_idempotent_success() -> None:
    prompts: list[str] = []
    finals: list[dict[str, Any]] = []
    advanced: list[dict[str, Any]] = []

    async def _run_loop(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        assert kwargs["idempotency_key"] == "idem-1"
        assert kwargs["canonical_response_id"] == "resp_idem"
        assert kwargs["stage_event_sink"] == "sink"
        return 200, {"id": "resp_idem", "object": "response", "status": "completed"}

    response = await execute_distributed_nonstream_response(
        model_provider=object(),
        tool_runtime=object(),
        agent_id="main",
        session_key="sess",
        body={"model": "gpt-test"},
        idempotency_key="idem-1",
        idem_created=True,
        idem_response_id="resp_idem",
        tool_context=None,
        manifest_resolver=_noop_manifest,
        manifest_force_refresh=_noop_manifest,
        mcp_manager=None,
        stage_event_sink="sink",
        append_prompt_context_event=lambda response_id: _record_prompt(prompts, response_id),
        finalize_nonstream_persisted=lambda **kwargs: _record(finals, kwargs),
        advance_nonstream_session_only=lambda **kwargs: _record(advanced, kwargs),
        new_response_id_factory=lambda: "resp_unused",
        run_tool_loop_nonstream_fn=_run_loop,
    )

    assert response.status_code == 200
    assert prompts == ["resp_idem"]
    assert advanced == []
    assert finals == [
        {
            "run_response_id": "resp_idem",
            "response_json": {"id": "resp_idem", "object": "response", "status": "completed"},
            "effective_status": "completed",
            "error_json": None,
            "resume_last_response_id": "resp_idem",
        }
    ]


def test_execute_distributed_nonstream_response_finalizes_idempotent_error() -> None:
    asyncio.run(_run_execute_distributed_nonstream_response_finalizes_idempotent_error())


async def _run_execute_distributed_nonstream_response_finalizes_idempotent_error() -> None:
    finals: list[dict[str, Any]] = []

    async def _run_loop(**_kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 502, {"error": {"message": "boom", "type": "upstream_error"}}

    response = await execute_distributed_nonstream_response(
        model_provider=object(),
        tool_runtime=object(),
        agent_id="main",
        session_key="sess",
        body={"model": "gpt-test"},
        idempotency_key="idem-err",
        idem_created=True,
        idem_response_id="resp_err",
        tool_context=None,
        manifest_resolver=_noop_manifest,
        manifest_force_refresh=_noop_manifest,
        mcp_manager=None,
        stage_event_sink=None,
        append_prompt_context_event=_noop_prompt_event,
        finalize_nonstream_persisted=lambda **kwargs: _record(finals, kwargs),
        advance_nonstream_session_only=lambda **kwargs: _record([], kwargs),
        new_response_id_factory=lambda: "resp_unused",
        run_tool_loop_nonstream_fn=_run_loop,
    )

    assert response.status_code == 502
    assert finals[0]["run_response_id"] == "resp_err"
    assert finals[0]["effective_status"] == "failed"
    assert finals[0]["error_json"] == {"message": "boom", "type": "upstream_error"}
    assert json.loads(finals[0]["error_event_data"]) == {"error": {"message": "boom", "type": "upstream_error"}}


def test_execute_distributed_stream_response_forwards_non_idempotent_stream() -> None:
    asyncio.run(_run_execute_distributed_stream_response_forwards_non_idempotent_stream())


async def _run_execute_distributed_stream_response_forwards_non_idempotent_stream() -> None:
    prompts: list[str] = []
    seen: list[dict[str, Any]] = []

    async def _run_stream(**kwargs: Any) -> Any:
        seen.append(kwargs)
        yield b"event: response.output_text.delta\ndata: {\"delta\":\"hi\"}\n\n"

    response = await execute_distributed_stream_response(
        model_provider=object(),
        tool_runtime=object(),
        agent_id="main",
        session_key="sess",
        body={"model": "gpt-test"},
        idempotency_key=None,
        idem_created=False,
        idem_response_id=None,
        storage=_storage(),
        storage_tasks=set(),
        session_partition_key="main::sess",
        tool_context=None,
        manifest_resolver=_noop_manifest,
        manifest_force_refresh=_noop_manifest,
        mcp_manager=None,
        stage_event_sink="sink",
        append_prompt_context_event=lambda response_id: _record_prompt(prompts, response_id),
        internal_event_writer=lambda **_kwargs: _int_none(),
        run_final_persister_builder=lambda _response_id: _record_final_state([]),
        new_response_id_factory=lambda: "resp_stream",
        run_tool_loop_stream_live_fn=_run_stream,
    )

    assert isinstance(response, StreamingResponse)
    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks == [b"event: response.output_text.delta\ndata: {\"delta\":\"hi\"}\n\n"]
    assert prompts == ["resp_stream"]
    assert seen[0]["canonical_response_id"] == "resp_stream"
    assert "stage_event_sink" not in seen[0]


def test_execute_distributed_stream_response_persists_idempotent_leader() -> None:
    asyncio.run(_run_execute_distributed_stream_response_persists_idempotent_leader())


async def _run_execute_distributed_stream_response_persists_idempotent_leader() -> None:
    storage = _storage()
    await storage.run_store.try_create_started(
        response_id="resp_stream_idem",
        session_partition_key="main::sess",
        idempotency_key="idem-stream",
        stream=True,
    )
    prompts: list[str] = []
    tasks: set[asyncio.Task[object]] = set()
    final_states: list[Any] = []

    async def _run_stream(**kwargs: Any) -> Any:
        assert kwargs["idempotency_key"] == "idem-stream"
        assert kwargs["canonical_response_id"] == "resp_stream_idem"
        assert kwargs["stage_event_sink"] == "sink"
        yield b"event: response.output_text.delta\ndata: {\"delta\":\"hi\"}\n\n"
        yield (
            b"event: response.completed\n"
            b"data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_stream_idem\",\"object\":\"response\",\"status\":\"completed\",\"model\":\"gpt-test\"}}\n\n"
        )
        yield b"data: [DONE]\n\n"

    response = await execute_distributed_stream_response(
        model_provider=object(),
        tool_runtime=object(),
        agent_id="main",
        session_key="sess",
        body={"model": "gpt-test"},
        idempotency_key="idem-stream",
        idem_created=True,
        idem_response_id="resp_stream_idem",
        storage=storage,
        storage_tasks=tasks,
        session_partition_key="main::sess",
        tool_context=None,
        manifest_resolver=_noop_manifest,
        manifest_force_refresh=_noop_manifest,
        mcp_manager=None,
        stage_event_sink="sink",
        append_prompt_context_event=lambda response_id: _record_prompt(prompts, response_id),
        internal_event_writer=lambda **kwargs: storage.event_store.append(
            session_partition_key="main::sess",
            **kwargs,
        ),
        run_final_persister_builder=lambda response_id: build_run_final_and_session_persister(
            run_store=storage.run_store,
            session_store=storage.session_store,
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            previous_snapshot=None,
            previous_snapshot_version=None,
            runtime_config={},
            request_transcript_items=[],
            response_id_resolver=lambda _state, rid=response_id: rid,
            warn=None,
        ),
        new_response_id_factory=lambda: "resp_unused",
        run_tool_loop_stream_live_fn=_run_stream,
    )

    assert isinstance(response, StreamingResponse)
    while tasks:
        await asyncio.gather(*tasks)
    assert prompts == ["resp_stream_idem"]
    run = await storage.run_store.get("resp_stream_idem")
    assert run is not None
    assert run.status == "completed"
    assert run.final_response_json is not None
    assert run.final_response_json["id"] == "resp_stream_idem"
    events = await storage.event_store.list(response_id="resp_stream_idem", after_seq=0, limit=10)
    assert [event.event for event in events] == ["response.output_text.delta", "response.completed", None]
    assert final_states == []


async def _record_prompt(target: list[str], response_id: str) -> None:
    target.append(response_id)


async def _record(target: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    target.append(payload)


async def _int_none() -> int | None:
    return None


def _record_final_state(target: list[Any]):
    async def _record_state(state: Any) -> None:
        target.append(state)

    return _record_state


def _storage() -> StorageRuntime:
    return StorageRuntime(
        mode="none",
        run_store=InMemoryRunStore(),
        event_store=InMemoryEventStore(),
        lease_lock=InMemoryLeaseLock(),
        session_store=InMemorySessionStore(),
    )
