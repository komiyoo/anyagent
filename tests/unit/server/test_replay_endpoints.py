"""Tests for M2/M3 replay behavior: persistence config, types re-export, replay router."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from anyagent.persistence.config import PersistenceConfig
from anyagent.persistence.model_request import ModelRequestPersistence
from anyagent.persistence.tool_execution import ToolExecutionPersistence
from anyagent.server.routes.internal_replay import create_internal_replay_router
from anyagent.server.responses.response_execution import (
    execute_distributed_nonstream_response,
    execute_distributed_stream_response,
)


class TestPersistenceConfigGating:
    def test_tool_execution_respects_own_toggle(self) -> None:
        config = PersistenceConfig(persist_tool_execution_detail=False)
        persistence = ToolExecutionPersistence(config=config)
        sink = AsyncMock()
        asyncio.run(persistence.persist(
            response_id="resp_1",
            tool_call_id="tc_1",
            tool_name="test_tool",
            arguments_json='{"x": 1}',
            output="ok",
            status="completed",
            stage_sink=sink,
        ))
        sink.assert_not_called()

    def test_tool_execution_writes_when_enabled(self) -> None:
        config = PersistenceConfig(persist_tool_execution_detail=True)
        persistence = ToolExecutionPersistence(config=config)
        sink = AsyncMock()
        asyncio.run(persistence.persist(
            response_id="resp_1",
            tool_call_id="tc_1",
            tool_name="test_tool",
            arguments_json='{"x": 1}',
            output="ok",
            status="completed",
            stage_sink=sink,
        ))
        sink.assert_called_once()
        event = sink.call_args[0][0]
        assert event.type == "anyagent.tool.execution.detail"

    def test_model_request_respects_own_toggle(self) -> None:
        config = PersistenceConfig(persist_model_request=False)
        persistence = ModelRequestPersistence(config=config)
        sink = AsyncMock()
        asyncio.run(persistence.persist(
            response_id="resp_1",
            applied_body={"model": "gpt-4", "input": []},
            stage_sink=sink,
        ))
        sink.assert_not_called()

    def test_model_request_writes_when_enabled(self) -> None:
        config = PersistenceConfig(persist_model_request=True)
        persistence = ModelRequestPersistence(config=config)
        sink = AsyncMock()
        asyncio.run(persistence.persist(
            response_id="resp_1",
            applied_body={"model": "gpt-4", "input": []},
            prompt_cache_key="cache-abc",
            stage_sink=sink,
        ))
        sink.assert_called_once()
        event = sink.call_args[0][0]
        assert event.type == "anyagent.model.request"
        assert event.applied_body == {"model": "gpt-4", "input": []}
        assert event.prompt_cache_key == "cache-abc"

    def test_model_request_redacts_sensitive_keys_before_storage(self) -> None:
        config = PersistenceConfig(persist_model_request=True)
        persistence = ModelRequestPersistence(config=config)
        sink = AsyncMock()
        asyncio.run(persistence.persist(
            response_id="resp_1",
            applied_body={
                "model": "gpt-4",
                "Authorization": "Bearer secret",
                "metadata": {"credential_id": "cred_demo", "safe": "ok"},
            },
            stage_sink=sink,
        ))

        event = sink.call_args[0][0]
        assert event.applied_body["Authorization"] == "[REDACTED]"
        assert event.applied_body["metadata"]["credential_id"] == "[REDACTED]"
        assert event.applied_body["metadata"]["safe"] == "ok"

    def test_rendered_context_toggle_does_not_gate_tool_execution(self) -> None:
        config = PersistenceConfig(
            persist_rendered_context=False,
            persist_tool_execution_detail=True,
        )
        persistence = ToolExecutionPersistence(config=config)
        sink = AsyncMock()
        asyncio.run(persistence.persist(
            response_id="resp_1",
            tool_call_id="tc_1",
            tool_name="test_tool",
            arguments_json="{}",
            status="completed",
            stage_sink=sink,
        ))
        sink.assert_called_once()


class TestTypesReExport:
    def test_new_stage_events_exported(self) -> None:
        from anyagent.types import (
            AnyAgentModelRequestEvent,
            AnyAgentToolExecutionDetailEvent,
        )
        assert AnyAgentModelRequestEvent is not None
        assert AnyAgentToolExecutionDetailEvent is not None

    def test_new_response_models_exported(self) -> None:
        from anyagent.types import (
            InternalResponseModelRequestResponse,
            InternalResponseToolExecutionsResponse,
        )
        assert InternalResponseModelRequestResponse is not None
        assert InternalResponseToolExecutionsResponse is not None


class _EventRow:
    def __init__(self, *, seq: int, data: dict[str, Any]) -> None:
        self.seq = seq
        self.data = json.dumps(data, ensure_ascii=False)


def test_internal_replay_prompt_context_uses_stage_event_type_names() -> None:
    asyncio.run(_run_internal_replay_prompt_context_uses_stage_event_type_names())


async def _run_internal_replay_prompt_context_uses_stage_event_type_names() -> None:
    app = FastAPI()
    app.include_router(create_internal_replay_router(api_key="user-key"))

    class _EventStore:
        async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[_EventRow]:
            assert response_id == "resp_replay"
            assert after_seq == 0
            assert limit == 500
            return [
                _EventRow(
                    seq=1,
                    data={
                        "type": "anyagent.prompt.context.rendered",
                        "response_id": "resp_replay",
                        "prompt_cache_key": "cache-replay",
                        "total_chars": 11,
                        "fragments": [
                            {
                                "kind": "environment_context",
                                "role": "developer",
                                "cache_class": "dynamic",
                                "rendered_text": "hello world",
                            }
                        ],
                    },
                )
            ]

    class _Storage:
        event_store = _EventStore()

    app.state.storage = _Storage()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.get(
            "/internal/responses/resp_replay/prompt-context",
            headers={"Authorization": "Bearer user-key"},
        )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["fallback"] == "rendered"
    assert payload["prompt_cache_key"] == "cache-replay"
    assert payload["fragments"][0]["rendered_text"] == "hello world"


def test_distributed_nonstream_passes_stage_sink_without_idempotency() -> None:
    asyncio.run(_run_distributed_nonstream_passes_stage_sink_without_idempotency())


async def _run_distributed_nonstream_passes_stage_sink_without_idempotency() -> None:
    emitted: list[Any] = []
    advanced: list[dict[str, Any]] = []

    async def _sink(event: Any) -> None:
        emitted.append(event)

    async def _noop_prompt(_response_id: str) -> None:
        return None

    async def _finalize(**_kwargs: Any) -> None:
        return None

    async def _advance(**kwargs: Any) -> None:
        advanced.append(kwargs)

    async def _manifest() -> tuple[list[dict[str, Any]], int]:
        return [], 1

    async def _run_tool_loop_nonstream_fn(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        assert kwargs["stage_event_sink"] is _sink
        return 200, {"id": "resp_generated", "object": "response", "status": "completed"}

    await execute_distributed_nonstream_response(
        model_provider=object(),
        tool_runtime=object(),
        agent_id="main",
        session_key="sess",
        body={"model": "gpt-test", "input": "hi"},
        idempotency_key=None,
        idem_created=False,
        idem_response_id=None,
        tool_context=None,
        manifest_resolver=_manifest,
        manifest_force_refresh=_manifest,
        mcp_manager=None,
        stage_event_sink=_sink,
        append_prompt_context_event=_noop_prompt,
        append_prompt_context_rendered_event=_noop_prompt,
        finalize_nonstream_persisted=_finalize,
        advance_nonstream_session_only=_advance,
        new_response_id_factory=lambda: "resp_generated",
        prompt_cache_key="cache-generated",
        run_tool_loop_nonstream_fn=_run_tool_loop_nonstream_fn,
    )

    assert emitted[0].type == "anyagent.model.request"
    assert emitted[0].response_id == "resp_generated"
    assert advanced


def test_distributed_stream_passes_stage_sink_without_idempotency() -> None:
    asyncio.run(_run_distributed_stream_passes_stage_sink_without_idempotency())


async def _run_distributed_stream_passes_stage_sink_without_idempotency() -> None:
    emitted: list[Any] = []
    saw_stage_sink = False

    async def _sink(event: Any) -> None:
        emitted.append(event)

    async def _noop_prompt(_response_id: str) -> None:
        return None

    async def _writer(**_kwargs: Any) -> int | None:
        return None

    async def _manifest() -> tuple[list[dict[str, Any]], int]:
        return [], 1

    async def _run_tool_loop_stream_live_fn(**kwargs: Any):
        nonlocal saw_stage_sink
        assert kwargs["stage_event_sink"] is _sink
        saw_stage_sink = True
        if False:
            yield b""

    response = await execute_distributed_stream_response(
        model_provider=object(),
        tool_runtime=object(),
        agent_id="main",
        session_key="sess",
        body={"model": "gpt-test", "input": "hi"},
        idempotency_key=None,
        idem_created=False,
        idem_response_id=None,
        storage=object(),
        storage_tasks=set(),
        session_partition_key="main::sess",
        tool_context=None,
        manifest_resolver=_manifest,
        manifest_force_refresh=_manifest,
        mcp_manager=None,
        stage_event_sink=_sink,
        append_prompt_context_event=_noop_prompt,
        append_prompt_context_rendered_event=_noop_prompt,
        internal_event_writer=_writer,
        run_final_persister_builder=lambda _response_id: None,
        new_response_id_factory=lambda: "resp_stream",
        prompt_cache_key="cache-stream",
        run_tool_loop_stream_live_fn=_run_tool_loop_stream_live_fn,
    )

    async for _chunk in response.body_iterator:
        pass

    assert emitted[0].type == "anyagent.model.request"
    assert emitted[0].response_id == "resp_stream"
    assert saw_stage_sink is True
