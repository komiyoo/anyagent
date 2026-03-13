from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from anyagent.protocol.sse import SSEBlockDecoder
from anyagent.server.app import _build_external_response_stream, _handle_sse_block, _update_session_snapshot, create_app
from anyagent.server.session_context import prepare_response_session_context


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".agents" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        """
exposed: true
tools:
  requested_tool_names: []
skills:
  default_selected: []
sandbox:
  mode: disabled
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_handle_sse_block_marks_final_and_appends_done() -> None:
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
            await _handle_sse_block(
                state=state,
                response_id="resp_integration_1",
                event="response.completed",
                data=json.dumps(
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_integration_1",
                            "object": "response",
                            "status": "completed",
                            "model": "gpt-4o-mini",
                            "output": [],
                        },
                    },
                    ensure_ascii=False,
                ),
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
