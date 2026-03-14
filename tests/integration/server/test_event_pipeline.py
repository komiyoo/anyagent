from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_created_event import ResponseCreatedEvent

from anyagent.protocol.sse import SSEBlockDecoder
from anyagent.server.app import _append_sse_chunk, _build_external_response_stream, _update_session_snapshot, create_app
from anyagent.server.session_context import prepare_response_session_context


def _write_workspace(
    root: Path,
    *,
    requested_tool_names: list[str] | None = None,
    sandbox_mode: str = "disabled",
) -> None:
    agent_dir = root / ".agents" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    requested_tool_values = [name.strip() for name in (requested_tool_names or []) if isinstance(name, str) and name.strip()]
    requested_tool_block = (
        ["  requested_tool_names: []"]
        if not requested_tool_values
        else ["  requested_tool_names:", *[f"    - {name}" for name in requested_tool_values]]
    )
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                *requested_tool_block,
                "skills:",
                "  default_selected: []",
                "sandbox:",
                f"  mode: {sandbox_mode}",
                "multiagent:",
                "  spawn_allow_agent_ids: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class _NoToolProvider:
    async def create_response(
        self,
        *,
        body: dict,
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        _ = idempotency_key, timeout_s
        return Response.model_validate(
            {
                "id": "resp_integration_provider",
                "object": "response",
                "created_at": 123,
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
        )

    async def create_response_stream_buffered(
        self,
        *,
        body: dict,
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[list, Response]:
        resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
        return [
            ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
            ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
        ], resp


class _RecordingProvider(_NoToolProvider):
    def __init__(self) -> None:
        self.seen_bodies: list[dict] = []

    async def create_response(
        self,
        *,
        body: dict,
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        self.seen_bodies.append(json.loads(json.dumps(body)))
        response = await super().create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s)
        payload = response.model_dump(exclude_none=True, by_alias=True)
        payload["id"] = f"resp_recorded_{len(self.seen_bodies)}"
        return Response.model_validate(payload)


def test_external_response_stream_completed_event_marks_final_and_appends_done() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
            state = app.state.anyagent

            await state.events.mark_started(response_id="resp_integration_1")
            await state.run_store.create_started(
                response_id="resp_integration_1",
                agent_id="main",
                session_key="sess-1",
                stream=True,
                idempotency_key=None,
            )
            decoder = SSEBlockDecoder()
            await _append_sse_chunk(
                state,
                response_id="resp_integration_1",
                chunk=(
                    b"event: response.completed\n"
                    b'data: {"type":"response.completed","response":{"id":"resp_integration_1","object":"response","status":"completed","model":"gpt-4o-mini","output":[]}}\n\n'
                    b"data: [DONE]\n\n"
                ),
                decoder=decoder,
                fallback_model="gpt-4o-mini",
            )

            listed = await state.events.list_events(response_id="resp_integration_1", last_seq=0, limit=10)
            run = await state.run_store.get("resp_integration_1")
            status, error = await state.events.get_status("resp_integration_1")

            assert [item.event for item in listed.events] == ["response.completed", None]
            assert listed.events[-1].data == "[DONE]"
            assert listed.done is True
            assert status == "completed"
            assert error is None
            assert run is not None
            assert run.status == "completed"
            assert run.effective_status == "completed"

    asyncio.run(_run())


def test_external_response_stream_filters_internal_events() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
            state = app.state.anyagent

            await state.events.append(
                response_id="resp_stream_1",
                event="response.created",
                data='{"type":"response.created","response":{"id":"resp_stream_1"}}',
            )
            await state.events.append(
                response_id="resp_stream_1",
                event="anyagent.tool.planned",
                data='{"type":"anyagent.tool.planned","response_id":"resp_stream_1","tool_call_id":"call_1","tool_name":"exec","arguments":{"bytes":1,"sha256":"a","preview":null,"preview_truncated":false}}',
            )
            await state.events.append(
                response_id="resp_stream_1",
                event="response.completed",
                data='{"type":"response.completed","response":{"id":"resp_stream_1","object":"response","status":"completed"}}',
            )
            await state.events.append(response_id="resp_stream_1", event=None, data="[DONE]")
            await state.events.mark_final(
                response_id="resp_stream_1",
                run_status="completed",
                effective_run_status="completed",
                response_json={"id": "resp_stream_1", "object": "response", "status": "completed"},
            )

            stream = _build_external_response_stream(state=state, response_id="resp_stream_1")
            chunks = []
            async for chunk in stream.body_iterator:
                chunks.append(chunk.decode("utf-8"))

            decoder = SSEBlockDecoder()
            blocks = []
            for part in chunks:
                for line in part.splitlines():
                    blocks.extend(decoder.feed_line(line))
            blocks.extend(decoder.flush())

            assert [(blk.id, blk.event, blk.data) for blk in blocks] == [
                ("1", "response.created", '{"type":"response.created","response":{"id":"resp_stream_1"}}'),
                (
                    "3",
                    "response.completed",
                    '{"type":"response.completed","response":{"id":"resp_stream_1","object":"response","status":"completed"}}',
                ),
                ("4", None, "[DONE]"),
            ]

    asyncio.run(_run())


def test_update_session_snapshot_roundtrip_applies_resume_state() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
            state = app.state.anyagent
            session_partition_key = "main::sess-roundtrip"

            session_ctx = await prepare_response_session_context(
                session_store=state.session_store,
                session_partition_key=session_partition_key,
                agent_id="main",
                session_key="sess-roundtrip",
                body={
                    "input": [{"role": "user", "content": "hello"}],
                    "model": "gpt-4.1-mini",
                    "temperature": 0.4,
                },
            )
            await state.events.append(
                response_id="resp_roundtrip_1",
                event="response.created",
                data='{"type":"response.created","response":{"id":"resp_roundtrip_1"}}',
            )
            await _update_session_snapshot(
                state=state,
                session_partition_key_value=session_partition_key,
                agent_id="main",
                session_key="sess-roundtrip",
                previous_snapshot=session_ctx.previous_snapshot,
                previous_snapshot_version=session_ctx.previous_snapshot_version,
                runtime_config=session_ctx.effective_runtime_config,
                request_transcript_items=session_ctx.request_transcript_items,
                response_id="resp_roundtrip_1",
                effective_status="completed",
                response_json={
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "world"}],
                        }
                    ]
                },
            )

            record = await state.session_store.get(session_partition_key=session_partition_key)
            assert record is not None
            assert record.snapshot_json["runtime_config"] == {"model": "gpt-4.1-mini", "temperature": 0.4}
            assert record.snapshot_json["resume_cursor"]["last_response_id"] == "resp_roundtrip_1"
            assert record.snapshot_json["last_run"]["last_event_seq"] == 1

            resumed = await prepare_response_session_context(
                session_store=state.session_store,
                session_partition_key=session_partition_key,
                agent_id="main",
                session_key="sess-roundtrip",
                body={"input": "next turn"},
            )

            assert resumed.previous_snapshot_version == 1
            assert resumed.effective_body["previous_response_id"] == "resp_roundtrip_1"
            assert resumed.effective_runtime_config == {"model": "gpt-4.1-mini", "temperature": 0.4}

    asyncio.run(_run())


def test_external_response_stream_includes_error_events() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
            state = app.state.anyagent

            await state.events.append(
                response_id="resp_stream_error_1",
                event="response.created",
                data='{"type":"response.created","response":{"id":"resp_stream_error_1"}}',
            )
            await state.events.append(
                response_id="resp_stream_error_1",
                event="anyagent.tool.result",
                data='{"type":"anyagent.tool.result","response_id":"resp_stream_error_1","tool_call_id":"call_1","tool_name":"exec","status":"error","meta":{"duration_ms":3,"output_truncated":false,"audit_ref":null},"error":{"type":"tool_execution_error","message":"boom"}}',
            )
            await state.events.append(
                response_id="resp_stream_error_1",
                event="error",
                data='{"error":{"message":"boom","type":"server_error"}}',
            )
            await state.events.append(response_id="resp_stream_error_1", event=None, data="[DONE]")
            await state.events.mark_final(
                response_id="resp_stream_error_1",
                run_status="errored",
                effective_run_status="errored",
                response_json=None,
                error=None,
            )

            stream = _build_external_response_stream(state=state, response_id="resp_stream_error_1")
            chunks = []
            async for chunk in stream.body_iterator:
                chunks.append(chunk.decode("utf-8"))

            decoder = SSEBlockDecoder()
            blocks = []
            for part in chunks:
                for line in part.splitlines():
                    blocks.extend(decoder.feed_line(line))
            blocks.extend(decoder.flush())

            assert [(blk.id, blk.event, blk.data) for blk in blocks] == [
                ("1", "response.created", '{"type":"response.created","response":{"id":"resp_stream_error_1"}}'),
                ("3", "error", '{"error":{"message":"boom","type":"server_error"}}'),
                ("4", None, "[DONE]"),
            ]

    asyncio.run(_run())


def test_create_response_reuses_manifest_cache_within_app_boundary() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
            runtime = app.state.anyagent.runtime
            original_manifest = runtime.manifest
            calls = {"manifest": 0}

            async def _manifest(req):
                calls["manifest"] += 1
                return await original_manifest(req)

            runtime.manifest = _manifest  # type: ignore[method-assign]
            try:
                import anyagent.server.app as server_app_module

                original_provider_factory = server_app_module.get_default_model_provider
                server_app_module.get_default_model_provider = lambda: _NoToolProvider()
                try:
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
                        body = {"model": "gpt-4o-mini", "input": "cache me", "metadata": {"session_key": "sess-cache"}}
                        resp1 = await client.post("/v1/responses", headers={"Authorization": "Bearer user-key"}, json=body)
                        resp2 = await client.post("/v1/responses", headers={"Authorization": "Bearer user-key"}, json=body)
                        assert resp1.status_code == 200, resp1.text
                        assert resp2.status_code == 200, resp2.text
                        assert calls["manifest"] == 1, calls
                finally:
                    server_app_module.get_default_model_provider = original_provider_factory
            finally:
                runtime.manifest = original_manifest  # type: ignore[method-assign]

    asyncio.run(_run())


def test_invalid_request_short_circuits_before_manifest_resolution() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
            runtime = app.state.anyagent.runtime
            calls = {"manifest": 0}
            original_manifest = runtime.manifest

            async def _manifest(req):
                calls["manifest"] += 1
                return await original_manifest(req)

            runtime.manifest = _manifest  # type: ignore[method-assign]
            try:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
                    resp = await client.post(
                        "/v1/responses",
                        headers={"Authorization": "Bearer user-key"},
                        json={"model": "gpt-4o-mini", "tools": {}},
                    )
                    assert resp.status_code == 400, resp.text
                    assert resp.json()["detail"] == "tools must be a list"
                    assert calls["manifest"] == 0, calls
            finally:
                runtime.manifest = original_manifest  # type: ignore[method-assign]

    asyncio.run(_run())


def test_internal_events_list_and_stream_respect_last_seq_limit_and_done_status() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
            state = app.state.anyagent
            response_id = "resp_list_stream_1"

            await state.events.mark_started(response_id=response_id)
            await state.events.append(
                response_id=response_id,
                event="response.created",
                data='{"type":"response.created","response":{"id":"resp_list_stream_1"}}',
            )
            await state.events.append(
                response_id=response_id,
                event="response.output_text.delta",
                data='{"type":"response.output_text.delta","item_id":"msg_1","output_index":0,"content_index":0,"delta":"hi","logprobs":[]}',
            )
            await state.events.append(
                response_id=response_id,
                event="response.completed",
                data='{"type":"response.completed","response":{"id":"resp_list_stream_1","object":"response","status":"completed"}}',
            )
            await state.events.append(response_id=response_id, event=None, data="[DONE]")
            await state.events.mark_final(
                response_id=response_id,
                run_status="completed",
                effective_run_status="completed",
                response_json={"id": response_id, "object": "response", "status": "completed"},
            )

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
                listed = await client.get(
                    "/internal/events/list",
                    headers={"Authorization": "Bearer user-key"},
                    params={"response_id": response_id, "last_seq": 1, "limit": 1},
                )
                assert listed.status_code == 200, listed.text
                payload = listed.json()
                assert payload["done"] is True
                assert payload["effective_run_status"] == "completed"
                assert payload["next_last_seq"] == 2
                assert [item["seq"] for item in payload["events"]] == [2]
                assert payload["events"][0]["event"] == "response.output_text.delta"

                listed_tail = await client.get(
                    "/internal/events/list",
                    headers={"Authorization": "Bearer user-key"},
                    params={"response_id": response_id, "last_seq": 99, "limit": 10},
                )
                assert listed_tail.status_code == 200, listed_tail.text
                tail_payload = listed_tail.json()
                assert tail_payload["events"] == []
                assert tail_payload["next_last_seq"] == 4
                assert tail_payload["done"] is True

                async with client.stream(
                    "GET",
                    "/internal/events/stream",
                    headers={"Authorization": "Bearer user-key"},
                    params={"response_id": response_id, "last_seq": 2},
                ) as resp:
                    assert resp.status_code == 200, resp.text
                    replay_text = (await resp.aread()).decode("utf-8")

            decoder = SSEBlockDecoder()
            blocks = []
            for line in replay_text.splitlines():
                blocks.extend(decoder.feed_line(line))
            blocks.extend(decoder.flush())

            assert [(blk.id, blk.event, blk.data) for blk in blocks] == [
                (
                    "3",
                    "response.completed",
                    '{"type":"response.completed","response":{"id":"resp_list_stream_1","object":"response","status":"completed"}}',
                ),
                ("4", None, "[DONE]"),
            ]

    asyncio.run(_run())


def test_retrieve_and_cancel_response_follow_optional_payload_semantics() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
            state = app.state.anyagent

            final_response_id = "resp_retrieve_final_1"
            final_payload = {
                "id": final_response_id,
                "object": "response",
                "created_at": 123,
                "model": "gpt-4o-mini",
                "output": [],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "status": "completed",
            }
            await state.run_store.create_started(
                response_id=final_response_id,
                agent_id="main",
                session_key="sess-retrieve",
                stream=False,
                idempotency_key=None,
            )
            await state.run_store.mark_final(
                response_id=final_response_id,
                status="completed",
                effective_status="completed",
                final_response_json=final_payload,
            )

            cancelled_response_id = "resp_cancelled_1"
            await state.events.mark_started(response_id=cancelled_response_id)
            await state.run_store.create_started(
                response_id=cancelled_response_id,
                agent_id="main",
                session_key="sess-cancel",
                stream=False,
                idempotency_key=None,
            )
            task = asyncio.create_task(asyncio.sleep(30))
            await state.runs.add(response_id=cancelled_response_id, task=task)

            transport = httpx.ASGITransport(app=app)
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
                    retrieved = await client.get(
                        f"/v1/responses/{final_response_id}",
                        headers={"Authorization": "Bearer user-key"},
                    )
                    assert retrieved.status_code == 200, retrieved.text
                    assert retrieved.json() == final_payload

                    cancel = await client.post(
                        f"/v1/responses/{cancelled_response_id}/cancel",
                        headers={"Authorization": "Bearer user-key"},
                    )
                    assert cancel.status_code == 200, cancel.text
                    cancel_payload = cancel.json()
                    assert cancel_payload["id"] == cancelled_response_id
                    assert cancel_payload["status"] == "cancelled"

                    retrieved_cancelled = await client.get(
                        f"/v1/responses/{cancelled_response_id}",
                        headers={"Authorization": "Bearer user-key"},
                    )
                    assert retrieved_cancelled.status_code == 200, retrieved_cancelled.text
                    assert retrieved_cancelled.json()["status"] == "cancelled"
            finally:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            run = await state.run_store.get(cancelled_response_id)
            status, error = await state.events.get_status(cancelled_response_id)
            assert run is not None
            assert run.status == "aborted"
            assert run.effective_status == "cancelled"
            assert status == "cancelled"
            assert error is None

    asyncio.run(_run())


def test_create_response_reuses_session_snapshot_across_app_boundary() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            provider = _RecordingProvider()

            import anyagent.server.app as server_app_module

            original_provider_factory = server_app_module.get_default_model_provider
            server_app_module.get_default_model_provider = lambda: provider
            try:
                app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
                    resp1 = await client.post(
                        "/v1/responses",
                        headers={"Authorization": "Bearer user-key"},
                        json={
                            "model": "gpt-4o-mini",
                            "temperature": 0.2,
                            "input": "hello",
                            "metadata": {"session_key": "sess-integration-session"},
                        },
                    )
                    assert resp1.status_code == 200, resp1.text
                    payload1 = resp1.json()

                    resp2 = await client.post(
                        "/v1/responses",
                        headers={"Authorization": "Bearer user-key"},
                        json={"input": "follow up", "metadata": {"session_key": "sess-integration-session"}},
                    )
                    assert resp2.status_code == 200, resp2.text

                assert len(provider.seen_bodies) == 2, provider.seen_bodies
                assert provider.seen_bodies[1]["previous_response_id"] == payload1["id"], provider.seen_bodies[1]
                assert provider.seen_bodies[1]["model"] == "gpt-4o-mini", provider.seen_bodies[1]
                assert provider.seen_bodies[1]["temperature"] == 0.2, provider.seen_bodies[1]
            finally:
                server_app_module.get_default_model_provider = original_provider_factory

    asyncio.run(_run())


def test_create_response_does_not_expose_unauthorized_exec_tool_to_provider() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root)
            provider = _RecordingProvider()

            import anyagent.server.app as server_app_module

            original_provider_factory = server_app_module.get_default_model_provider
            server_app_module.get_default_model_provider = lambda: provider
            try:
                app = create_app(workspace_dir=root, api_key="user-key", admin_api_key="admin-key")
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
                    resp = await client.post(
                        "/v1/responses",
                        headers={"Authorization": "Bearer user-key"},
                        json={
                            "model": "gpt-4o-mini",
                            "input": "try exec",
                            "tools": [
                                {
                                    "type": "function",
                                    "name": "exec",
                                    "description": "shell access",
                                    "parameters": {"type": "object", "properties": {}},
                                }
                            ],
                            "metadata": {
                                "context": {
                                    "policy": {
                                        "allow_tools": ["exec"],
                                    }
                                }
                            },
                        },
                    )
                    assert resp.status_code == 200, resp.text

                assert len(provider.seen_bodies) == 1, provider.seen_bodies
                assert provider.seen_bodies[0]["tools"] == [], provider.seen_bodies[0]
            finally:
                server_app_module.get_default_model_provider = original_provider_factory

    asyncio.run(_run())


def test_internal_tool_execute_rejects_malformed_arguments() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_workspace(root, requested_tool_names=["exec"], sandbox_mode="local-unsafe")
            app = create_app(
                workspace_dir=root,
                api_key="user-key",
                admin_api_key="admin-key",
                sandbox_root_dir=root / ".sandbox",
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
                invalid_arguments = await client.post(
                    "/internal/tools/execute",
                    headers={"Authorization": "Bearer admin-key"},
                    json={
                        "agent_id": "main",
                        "session_key": "sess-malformed",
                        "response_id": "resp-malformed-1",
                        "tool_call_id": "call-malformed-1",
                        "tool_name": "exec",
                        "arguments_json": [],
                        "context": {},
                    },
                )
                assert invalid_arguments.status_code == 200, invalid_arguments.text
                invalid_payload = invalid_arguments.json()
                assert invalid_payload["status"] == "error"
                assert invalid_payload["error"]["code"] == "invalid_arguments"

                schema_error = await client.post(
                    "/internal/tools/execute",
                    headers={"Authorization": "Bearer admin-key"},
                    json={
                        "agent_id": "main",
                        "session_key": "sess-malformed",
                        "response_id": "resp-malformed-2",
                        "tool_call_id": "call-malformed-2",
                        "tool_name": "exec",
                        "arguments_json": {"timeout": 1},
                        "context": {},
                    },
                )
                assert schema_error.status_code == 200, schema_error.text
                schema_payload = schema_error.json()
                assert schema_payload["status"] == "error"
                assert schema_payload["error"]["code"] == "schema_validation_error"

    asyncio.run(_run())
