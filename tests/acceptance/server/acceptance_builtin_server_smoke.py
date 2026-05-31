from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest
from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_created_event import ResponseCreatedEvent
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.server.app import create_app
from anyagent.server.handlers.sse_blocks import _build_created_sse_block
from anyagent.server.db.migrations import apply_storage_migrations
from anyagent.server.persistence.events import (
    CachedEventStore,
    InMemoryEventStore,
    PostgresEventStore,
    RedisEventStore,
    build_redis_event_list_key,
    build_redis_event_meta_key,
)
from anyagent.server.runtime.lock_service import (
    ExternalSessionLockService,
    InMemorySessionLockService,
    RedisSessionLockClient,
    SessionLeaseConflict,
    SessionLeaseRecord,
    build_redis_session_lock_key,
    build_session_lock_service,
    hold_session_lease,
)
from anyagent.protocol.sse import parse_sse_events
from anyagent.server.persistence.run_store import (
    CachedRunStore,
    InMemoryRunStore,
    PostgresRunStore,
    RedisRunStore,
    build_redis_run_store_idempotency_key,
    build_redis_run_store_key,
)
from anyagent.server.config.settings import ServerSettings
from anyagent.server.persistence.session_store import (
    CachedSessionStore,
    InMemorySessionStore,
    PostgresSessionStore,
    RedisSessionStore,
    SessionSnapshotVersionConflict,
    build_redis_session_store,
    build_redis_session_store_key,
)
from anyagent.protocol.tool_runtime import ManifestResponse


class _FakeProvider:
    def __init__(self) -> None:
        self._turn = 0

    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        model = str(body.get("model") or "gpt-4o-mini")
        if self._turn == 0:
            self._turn += 1
            payload = {
                "id": "resp_fake_run",
                "object": "response",
                "created_at": int(time.time()),
                "model": model,
                "output": [
                    ResponseFunctionToolCall(
                        type="function_call",
                        call_id="call_exec_1",
                        name="exec",
                        arguments=json.dumps({"cmd": "printf hello", "workdir": "work", "timeout": 2}, ensure_ascii=False),
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
            }
            return Response.model_validate(payload)

        payload = {
            "id": "resp_followup_internal",
            "object": "response",
            "created_at": int(time.time()),
            "model": model,
            "output": [
                ResponseOutputMessage(
                    id="msg_done",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text="done", annotations=[])],
                ).model_dump(exclude_none=True, by_alias=True)
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": list(body.get("tools") or []),
            "status": "completed",
        }
        return Response.model_validate(payload)

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


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        """
exposed: true
tools:
  requested_tool_names:
    - exec
skills:
  default_selected: []
sandbox:
  mode: local-unsafe
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_workspace_without_exec(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        """
exposed: true
tools:
  requested_tool_names: []
skills:
  default_selected: []
sandbox:
  mode: local-unsafe
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _prepare_live_postgres_schema(*, monkeypatch, postgres_dsn: str) -> str:
    schema = f"test_{int(time.time() * 1000)}"
    monkeypatch.setenv("POSTGRES_DSN", postgres_dsn)
    monkeypatch.setenv("POSTGRES_SCHEMA", schema)
    monkeypatch.setenv("POSTGRES_SCHEMA_POLICY", "migrate")
    apply_storage_migrations(
        postgres_dsn=postgres_dsn,
        postgres_schema=schema,
        dry_run=False,
    )
    return schema


def _write_workspace_opensandbox(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        """
exposed: true
tools:
  requested_tool_names:
    - exec
skills:
  default_selected: []
sandbox:
  mode: opensandbox
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_builtin_server_exec_and_events_smoke(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_builtin_server_exec_and_events_smoke(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_builtin_server_exec_and_events_smoke(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        auth = {"Authorization": "Bearer user-key"}
        admin_auth = {"Authorization": "Bearer admin-key"}

        health = await client.get("/healthz")
        assert health.status_code == 200

        manifest = await client.post(
            "/internal/tools/manifest",
            headers=admin_auth,
            json={"agent_id": "main", "session_key": "sess-1", "requested_tool_names": ["exec"]},
        )
        assert manifest.status_code == 200
        manifest_json = manifest.json()
        assert manifest_json["tools"][0]["name"] == "exec"
        assert manifest_json["tools"][0]["x-anyagent-kind"] == "command"

        resp = await client.post(
            "/v1/responses",
            headers=auth,
            json={
                "model": "gpt-4o-mini",
                "input": "run something",
                "metadata": {"session_key": "sess-1"},
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["id"].startswith("resp_")
        assert payload["status"] == "completed"
        response_id = payload["id"]

        events = await client.get(
            "/internal/events/list",
            headers=auth,
            params={"response_id": response_id, "last_seq": 0, "limit": 50},
        )
        assert events.status_code == 200
        data = events.json()
        event_names = [item.get("event") for item in data["events"]]
        assert "anyagent.tool.planned" in event_names
        assert "anyagent.tool.result" in event_names
        assert "anyagent.command.planned" in event_names
        assert "anyagent.command.result" in event_names
        assert "response.completed" in event_names

        set_cred = await client.post(
            "/admin/credentials",
            headers=admin_auth,
            json={
                "credential_id": "cred_test",
                "kind": "bearer_token",
                "value": "secret-value",
                "scope": {"level": "global"},
                "metadata": {"display_name": "Test"},
            },
        )
        assert set_cred.status_code == 200

        list_cred = await client.get("/admin/credentials", headers=admin_auth)
        assert list_cred.status_code == 200
        creds = list_cred.json()["credentials"]
        assert creds[0]["credential_id"] == "cred_test"
        assert "value" not in creds[0]


def test_builtin_server_ignores_caller_policy_for_exec(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_builtin_server_ignores_caller_policy_for_exec(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_builtin_server_ignores_caller_policy_for_exec(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace_without_exec(tmp_path)

    observed_tools: list[str] = []

    class _ObserveProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = idempotency_key, timeout_s
            observed_tools[:] = [tool.get("name") for tool in body.get("tools") or [] if isinstance(tool, dict)]
            payload = {
                "id": "resp_no_exec",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id="msg_no_exec",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="no tools", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _ObserveProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
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
                        "description": "caller wants exec",
                        "parameters": {
                            "type": "object",
                            "properties": {"cmd": {"type": "string"}},
                            "required": ["cmd"],
                            "additionalProperties": False,
                        },
                    }
                ],
                "metadata": {
                    "session_key": "sess-2",
                    "context": {"policy": {"allow_tools": ["exec"]}},
                },
            },
        )
        assert resp.status_code == 200, resp.text
        assert "exec" not in observed_tools, observed_tools


def test_builtin_server_opensandbox_requires_base_url(tmp_path: Path, monkeypatch) -> None:
    _write_workspace_opensandbox(tmp_path)
    monkeypatch.delenv("OPENSANDBOX_BASE_URL", raising=False)
    try:
        create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    except RuntimeError as e:
        assert "opensandbox backend requires OPENSANDBOX_BASE_URL" in str(e)
        return
    raise AssertionError("create_app should require OPENSANDBOX_BASE_URL when sandbox.mode=opensandbox")


def test_stream_created_block_shape() -> None:
    block = _build_created_sse_block(
        response_id="resp_test_created",
        body={"model": "gpt-4o-mini", "tool_choice": "auto"},
    )
    events = parse_sse_events(block.decode("utf-8"))
    assert events and events[0][0] == "response.created"
    payload = json.loads(events[0][1])
    assert payload["response"]["id"] == "resp_test_created"
    assert payload["response"]["status"] == "in_progress"

def test_builtin_server_nonstream_best_effort_cancel(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_builtin_server_nonstream_best_effort_cancel(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_builtin_server_nonstream_best_effort_cancel(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)

    class _BlockingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = body, idempotency_key, timeout_s
            await asyncio.sleep(30)
            raise AssertionError("provider should be cancelled before completion")

    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _BlockingProvider())
    monkeypatch.setattr("anyagent.server.routes.responses.uuid.uuid4", lambda: type("_U", (), {"hex": "canceltest"})())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as cancel_client:
            run_task = asyncio.create_task(
                client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={
                "model": "gpt-4o-mini",
                "input": "please cancel me",
                "metadata": {"session_key": "sess-cancel"},
            },
                )
            )
            await asyncio.sleep(0.1)
            response_id = "resp_canceltest"
            cancel = await cancel_client.post(
                f"/v1/responses/{response_id}/cancel",
                headers={"Authorization": "Bearer user-key"},
            )
            assert cancel.status_code == 200, cancel.text
            cancel_payload = cancel.json()
            assert cancel_payload["status"] == "cancelled", cancel_payload
            resp = await run_task
            assert resp.status_code == 200, resp.text
            payload = resp.json()
            assert payload["id"] == response_id, payload
            assert payload["status"] == "cancelled", payload


def test_internal_events_stream_replays_and_tails(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_internal_events_stream_replays_and_tails(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_internal_events_stream_replays_and_tails(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    response_id = "resp_event_stream"
    await app.state.anyagent.events.mark_started(response_id=response_id)
    await app.state.anyagent.run_store.create_started(
        response_id=response_id,
        agent_id="main",
        session_key="sess-event-stream",
        stream=True,
        idempotency_key=None,
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.tool.planned",
        data=json.dumps({"type": "anyagent.tool.planned", "response_id": response_id, "tool_call_id": "call_1", "tool_name": "exec", "arguments": {"bytes": 2, "sha256": "x"}}),
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.tool.result",
        data=json.dumps({"type": "anyagent.tool.result", "response_id": response_id, "tool_call_id": "call_1", "tool_name": "exec", "status": "completed", "meta": {}}),
    )
    await app.state.anyagent.events.mark_final(
        response_id=response_id,
        run_status="completed",
        response_json={"id": response_id, "object": "response", "status": "completed"},
    )
    await app.state.anyagent.run_store.mark_final(
        response_id=response_id,
        status="completed",
        effective_status="completed",
        final_response_json={"id": response_id, "object": "response", "status": "completed"},
    )
    await app.state.anyagent.events.append(response_id=response_id, event=None, data="[DONE]")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        async with client.stream(
            "GET",
            "/internal/events/stream",
            headers={"Authorization": "Bearer user-key"},
            params={"response_id": response_id, "last_seq": 0},
        ) as resp:
            assert resp.status_code == 200, resp.text
            text = await resp.aread()
            events = parse_sse_events(text.decode("utf-8"))
            names = [event for event, _ in events]
            assert "anyagent.tool.planned" in names, names
            assert "anyagent.tool.result" in names, names
            assert any(data == "[DONE]" for event, data in events if event is None), events


def test_internal_tool_cancel_cancels_active_exec(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_internal_tool_cancel_cancels_active_exec(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_internal_tool_cancel_cancels_active_exec(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        execute_task = asyncio.create_task(
            client.post(
                "/internal/tools/execute",
                headers={"Authorization": "Bearer admin-key"},
                json={
                    "agent_id": "main",
                    "session_key": "sess-tool-cancel",
                    "response_id": "resp_tool_cancel",
                    "tool_call_id": "call_exec_cancel",
                    "tool_name": "exec",
                    "arguments_json": {"cmd": "sleep 30", "timeout": 60},
                    "context": {},
                },
            )
        )
        await asyncio.sleep(0.2)
        cancel = await client.post(
            "/internal/tools/cancel",
            headers={"Authorization": "Bearer admin-key"},
            json={
                "response_id": "resp_tool_cancel",
                "tool_call_id": "call_exec_cancel",
            },
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["ok"] is True

        execute_resp = await execute_task
        assert execute_resp.status_code == 200, execute_resp.text
        payload = execute_resp.json()
        assert payload["status"] == "cancelled", payload
        assert payload["error"]["code"] == "tool_cancelled", payload


def test_internal_tool_execute_idempotent_after_completion(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_internal_tool_execute_idempotent_after_completion(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_internal_tool_execute_idempotent_after_completion(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    req_json = {
        "agent_id": "main",
        "session_key": "sess-idem-done",
        "response_id": "resp_idem_done",
        "tool_call_id": "call_exec_done",
        "tool_name": "exec",
        "arguments_json": {"cmd": "printf hi", "timeout": 5},
        "context": {},
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post("/internal/tools/execute", headers={"Authorization": "Bearer admin-key"}, json=req_json)
        resp2 = await client.post("/internal/tools/execute", headers={"Authorization": "Bearer admin-key"}, json=req_json)
        assert resp1.status_code == 200, resp1.text
        assert resp2.status_code == 200, resp2.text
        payload1 = resp1.json()
        payload2 = resp2.json()
        assert payload1 == payload2
        assert payload1["status"] == "completed"
        assert payload1["meta"]["audit_ref"].startswith("aud_"), payload1
        assert payload1["meta"]["audit_ref"] == payload2["meta"]["audit_ref"], (payload1, payload2)


def test_internal_tool_execute_idempotent_while_running(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_internal_tool_execute_idempotent_while_running(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_internal_tool_execute_idempotent_while_running(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    req_json = {
        "agent_id": "main",
        "session_key": "sess-idem-run",
        "response_id": "resp_idem_run",
        "tool_call_id": "call_exec_run",
        "tool_name": "exec",
        "arguments_json": {"cmd": "sleep 30", "timeout": 60},
        "context": {},
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        first = asyncio.create_task(
            client.post("/internal/tools/execute", headers={"Authorization": "Bearer admin-key"}, json=req_json)
        )
        await asyncio.sleep(0.2)
        second = await client.post("/internal/tools/execute", headers={"Authorization": "Bearer admin-key"}, json=req_json)
        assert second.status_code == 200, second.text
        payload = second.json()
        assert payload["status"] == "error", payload
        assert payload["error"]["code"] == "tool_execution_in_progress", payload
        assert payload["error"]["retryable"] is True, payload
        cancel = await client.post(
            "/internal/tools/cancel",
            headers={"Authorization": "Bearer admin-key"},
            json={"response_id": "resp_idem_run", "tool_call_id": "call_exec_run"},
        )
        assert cancel.status_code == 200
        execute_resp = await first
        assert execute_resp.status_code == 200
        assert execute_resp.json()["status"] == "cancelled"


def test_internal_tools_execute_returns_409_on_toolset_version_mismatch(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_internal_tools_execute_returns_409_on_toolset_version_mismatch(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_internal_tools_execute_returns_409_on_toolset_version_mismatch(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp = await client.post(
            "/internal/tools/execute",
            headers={"Authorization": "Bearer admin-key"},
            json={
                "agent_id": "main",
                "session_key": "sess-mismatch",
                "response_id": "resp_mismatch",
                "tool_call_id": "call_mismatch",
                "tool_name": "exec",
                "arguments_json": {"cmd": "printf hi", "timeout": 5},
                "toolset_version": 999,
                "context": {},
            },
        )
        assert resp.status_code == 409, resp.text
        payload = resp.json()
        assert payload["status"] == "error", payload
        assert payload["error"]["code"] == "toolset_version_mismatch", payload
        assert payload["error"]["retryable"] is True, payload


def test_agent_loop_retries_once_on_toolset_version_mismatch(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_agent_loop_retries_once_on_toolset_version_mismatch(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_agent_loop_retries_once_on_toolset_version_mismatch(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )

    runtime = app.state.anyagent.runtime
    original_manifest = runtime.manifest
    calls = {"manifest": 0}

    async def _manifest(req):
        calls["manifest"] += 1
        resp = await original_manifest(req)
        if calls["manifest"] == 1:
            return ManifestResponse(
                tools=resp.tools,
                toolset_version=max(resp.toolset_version - 1, 1),
                decisions=resp.decisions,
            )
        return resp

    monkeypatch.setattr(runtime, "manifest", _manifest)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={
                "model": "gpt-4o-mini",
                "input": "run something",
                "metadata": {"session_key": "sess-retry"},
            },
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["status"] == "completed", payload
        assert calls["manifest"] == 2, calls


def test_manifest_cache_hits_within_ttl(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_manifest_cache_hits_within_ttl(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_manifest_cache_hits_within_ttl(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    runtime = app.state.anyagent.runtime
    original_manifest = runtime.manifest
    calls = {"manifest": 0}

    async def _manifest(req):
        calls["manifest"] += 1
        return await original_manifest(req)

    monkeypatch.setattr(runtime, "manifest", _manifest)

    transport = httpx.ASGITransport(app=app)
    req_json = {
        "model": "gpt-4o-mini",
        "input": "run something",
        "metadata": {"session_key": "sess-cache"},
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post("/v1/responses", headers={"Authorization": "Bearer user-key"}, json=req_json)
        resp2 = await client.post("/v1/responses", headers={"Authorization": "Bearer user-key"}, json=req_json)
        assert resp1.status_code == 200, resp1.text
        assert resp2.status_code == 200, resp2.text
        assert calls["manifest"] == 1, calls


def test_nonstream_idempotency_returns_cached_final_response(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_nonstream_idempotency_returns_cached_final_response(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_nonstream_idempotency_returns_cached_final_response(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)

    class _SimpleFinalProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = body, idempotency_key, timeout_s
            self.calls += 1
            payload = {
                "id": "resp_upstream_simple",
                "object": "response",
                "created_at": int(time.time()),
                "model": "gpt-4o-mini",
                "output": [
                    ResponseOutputMessage(
                        id="msg_cached",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="cached", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": [],
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    provider = _SimpleFinalProvider()
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: provider)
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    req_json = {"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": "sess-idem-api"}}
    headers = {"Authorization": "Bearer user-key", "Idempotency-Key": "idem-1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post("/v1/responses", headers=headers, json=req_json)
        resp2 = await client.post("/v1/responses", headers=headers, json=req_json)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()
        assert provider.calls == 1, provider.calls


def test_stream_idempotency_replays_persisted_events(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_stream_idempotency_replays_persisted_events(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_stream_idempotency_replays_persisted_events(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _FakeProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer user-key", "Idempotency-Key": "idem-stream-1"}
    req_json = {
        "model": "gpt-4o-mini",
        "input": "run something",
        "stream": True,
        "metadata": {"session_key": "sess-idem-stream"},
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        async with client.stream("POST", "/v1/responses", headers=headers, json=req_json) as first:
            text1 = (await first.aread()).decode("utf-8")
        async with client.stream("POST", "/v1/responses", headers=headers, json=req_json) as second:
            text2 = (await second.aread()).decode("utf-8")
        events1 = parse_sse_events(text1)
        events2 = parse_sse_events(text2)
        names2 = [event for event, _ in events2]
        assert "response.completed" in names2, events2
        assert any(data == "[DONE]" for event, data in events2 if event is None), events2
        assert len(events2) >= 2


def test_session_runtime_config_reused_across_requests(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_session_runtime_config_reused_across_requests(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_session_runtime_config_reused_across_requests(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    seen_bodies: list[dict] = []

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = idempotency_key, timeout_s
            seen_bodies.append(json.loads(json.dumps(body)))
            payload = {
                "id": f"resp_record_{len(seen_bodies)}",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id=f"msg_{len(seen_bodies)}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"model": "gpt-4o-mini", "temperature": 0.2, "input": "hello", "metadata": {"session_key": "sess-session-1"}},
        )
        resp2 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"input": "follow up", "metadata": {"session_key": "sess-session-1"}},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert len(seen_bodies) == 2, seen_bodies
        assert seen_bodies[1]["model"] == "gpt-4o-mini", seen_bodies[1]
        assert seen_bodies[1]["temperature"] == 0.2, seen_bodies[1]


def test_admin_storage_health_reports_backends(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_admin_storage_health_reports_backends(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_admin_storage_health_reports_backends(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent")
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("STORAGE_MODE", "external")
    monkeypatch.setattr("anyagent.server.handlers.storage_health._check_postgres_connection", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
    monkeypatch.setattr("anyagent.server.handlers.storage_health._check_redis_connection", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp = await client.get("/admin/storage/health", headers={"Authorization": "Bearer admin-key"})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["ok"] is True
        assert payload["storage_mode"] == "external"
        assert payload["backends"]["event_store"] == "external"
        assert payload["backends"]["run_store"] == "external"
        assert payload["backends"]["session_store"] == "external"
        assert payload["postgres"]["reachable"] is True
        assert payload["redis"]["reachable"] is True
        assert payload["stores"]["events"]["type"] in {"CachedEventStore", "RedisEventStore"}
        assert payload["capabilities"]["event_store"]["tier"] == "external"
        assert payload["capabilities"]["event_store"]["long_term_owner"] == "anyagent-apps"
        assert payload["capabilities"]["run_store"]["supports_idempotency"] is True
        assert payload["capabilities"]["session_lock"]["supports_keyed_serialization"] is True


def test_storage_migrations_apply_live(monkeypatch) -> None:
    postgres_dsn = os.getenv("ANYAGENT_TEST_POSTGRES_DSN")
    if not postgres_dsn or not postgres_dsn.strip():
        pytest.skip("ANYAGENT_TEST_POSTGRES_DSN not set")
    schema = f"mig_{int(time.time() * 1000)}"
    result = apply_storage_migrations(
        postgres_dsn=postgres_dsn.strip(),
        postgres_schema=schema,
        dry_run=False,
    )
    assert "0001_storage_core" in result["planned"]
    assert "0001_storage_core" in result["applied"]
    result2 = apply_storage_migrations(
        postgres_dsn=postgres_dsn.strip(),
        postgres_schema=schema,
        dry_run=False,
    )
    assert result2["applied"] == []


def test_storage_migrate_dry_run_without_dsn(monkeypatch) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    result = apply_storage_migrations(dry_run=True)
    assert result["schema"] == "public"
    assert result["planned"]
    assert result["applied"] == []


def test_postgres_store_requires_migration_first_live(tmp_path: Path, monkeypatch) -> None:
    postgres_dsn = os.getenv("ANYAGENT_TEST_POSTGRES_DSN")
    redis_dsn = os.getenv("ANYAGENT_TEST_REDIS_DSN")
    if not postgres_dsn or not postgres_dsn.strip() or not redis_dsn or not redis_dsn.strip():
        pytest.skip("ANYAGENT_TEST_POSTGRES_DSN / ANYAGENT_TEST_REDIS_DSN not set")
    _write_workspace(tmp_path)
    schema = f"nomig_{int(time.time() * 1000)}"
    monkeypatch.setenv("POSTGRES_DSN", postgres_dsn.strip())
    monkeypatch.setenv("POSTGRES_SCHEMA", schema)
    monkeypatch.setenv("POSTGRES_SCHEMA_POLICY", "migrate")
    monkeypatch.setenv("REDIS_DSN", redis_dsn.strip())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="inmemory",
        session_store_backend="external",
    )

    async def _check() -> None:
        with pytest.raises(RuntimeError, match="storage migrate"):
            await app.state.anyagent.session_store.get(session_partition_key="main::no-mig")

    asyncio.run(_check())


def test_session_previous_response_id_injected_from_snapshot(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_session_previous_response_id_injected_from_snapshot(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_session_previous_response_id_injected_from_snapshot(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    seen_bodies: list[dict] = []

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = idempotency_key, timeout_s
            seen_bodies.append(json.loads(json.dumps(body)))
            payload = {
                "id": f"resp_record_prev_{len(seen_bodies)}",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id=f"msg_prev_{len(seen_bodies)}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": "sess-session-2"}},
        )
        payload1 = resp1.json()
        resp2 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"input": "follow up", "metadata": {"session_key": "sess-session-2"}},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert len(seen_bodies) == 2, seen_bodies
        assert seen_bodies[1]["previous_response_id"] == payload1["id"], seen_bodies[1]


def test_session_store_rejects_stale_snapshot_version() -> None:
    asyncio.run(_run_session_store_rejects_stale_snapshot_version())


async def _run_session_store_rejects_stale_snapshot_version() -> None:
    store = InMemorySessionStore()
    record1 = await store.upsert(
        session_partition_key="main::sess-cas",
        agent_id="main",
        session_key="sess-cas",
        snapshot_json={"runtime_config": {"model": "gpt-4o-mini"}},
        expected_snapshot_version=None,
    )
    record2 = await store.upsert(
        session_partition_key="main::sess-cas",
        agent_id="main",
        session_key="sess-cas",
        snapshot_json={"runtime_config": {"model": "gpt-4.1-mini"}},
        expected_snapshot_version=record1.snapshot_version,
    )
    try:
        await store.upsert(
            session_partition_key="main::sess-cas",
            agent_id="main",
            session_key="sess-cas",
            snapshot_json={"runtime_config": {"model": "gpt-4.1"}},
            expected_snapshot_version=record1.snapshot_version,
        )
    except SessionSnapshotVersionConflict as exc:
        assert exc.expected_snapshot_version == record1.snapshot_version
        assert exc.actual_snapshot_version == record2.snapshot_version
    else:
        raise RuntimeError("expected SessionSnapshotVersionConflict")

    latest = await store.get(session_partition_key="main::sess-cas")
    assert latest is not None
    assert latest.snapshot_version == record2.snapshot_version
    assert latest.snapshot_json["runtime_config"]["model"] == "gpt-4.1-mini"


def test_redis_session_store_upsert_and_cas_via_adapter() -> None:
    asyncio.run(_run_redis_session_store_upsert_and_cas_via_adapter())


async def _run_redis_session_store_upsert_and_cas_via_adapter() -> None:
    calls: list[tuple] = []
    state: dict[str, dict[str, str]] = {}

    class _Adapter:
        async def hgetall(self, key: str) -> dict[str, str]:
            calls.append(("hgetall", key))
            return dict(state.get(key) or {})

        async def eval(self, script: str, numkeys: int, *keys_and_args):
            calls.append(("eval", script, numkeys, *keys_and_args))
            key = str(keys_and_args[0])
            expected = str(keys_and_args[1])
            agent_id = str(keys_and_args[2])
            session_key = str(keys_and_args[3])
            snapshot_json = str(keys_and_args[4])
            current = state.get(key)
            current_version = None if current is None else int(current["snapshot_version"])
            if expected == "__none__":
                matches = current_version is None
            else:
                matches = current_version is not None and current_version == int(expected)
            if not matches:
                return [0, "__none__" if current_version is None else str(current_version), ""]
            next_version = 0 if current_version is None else current_version + 1
            state[key] = {
                "agent_id": agent_id,
                "session_key": session_key,
                "snapshot_json": snapshot_json,
                "snapshot_version": str(next_version),
            }
            return [1, str(next_version)]

        async def pexpire(self, key: str, time_ms: int) -> int:
            calls.append(("pexpire", key, time_ms))
            return 1

    store = RedisSessionStore(
        redis_dsn="redis://localhost:6379/0",
        namespace="demo",
        adapter=_Adapter(),
    )
    key = build_redis_session_store_key(namespace="demo", session_partition_key="main::sess-redis-store")
    record1 = await store.upsert(
        session_partition_key="main::sess-redis-store",
        agent_id="main",
        session_key="sess-redis-store",
        snapshot_json={"runtime_config": {"model": "gpt-4o-mini"}},
        expected_snapshot_version=None,
    )
    got1 = await store.get(session_partition_key="main::sess-redis-store")
    assert got1 is not None and got1.snapshot_version == 0
    record2 = await store.upsert(
        session_partition_key="main::sess-redis-store",
        agent_id="main",
        session_key="sess-redis-store",
        snapshot_json={"runtime_config": {"model": "gpt-4.1-mini"}},
        expected_snapshot_version=record1.snapshot_version,
    )
    try:
        await store.upsert(
            session_partition_key="main::sess-redis-store",
            agent_id="main",
            session_key="sess-redis-store",
            snapshot_json={"runtime_config": {"model": "gpt-4.1"}},
            expected_snapshot_version=record1.snapshot_version,
        )
    except SessionSnapshotVersionConflict as exc:
        assert exc.actual_snapshot_version == record2.snapshot_version
    else:
        raise RuntimeError("expected SessionSnapshotVersionConflict")
    assert state[key]["snapshot_version"] == "1"
    assert calls[0][0] == "eval"
    assert calls[1][0] == "pexpire" and calls[1][1] == key
    assert calls[2] == ("hgetall", key)


def test_redis_run_store_roundtrip_via_adapter() -> None:
    asyncio.run(_run_redis_run_store_roundtrip_via_adapter())


async def _run_redis_run_store_roundtrip_via_adapter() -> None:
    calls: list[tuple] = []
    hashes: dict[str, dict[str, str]] = {}
    strings: dict[str, str] = {}
    sorted_sets: dict[str, dict[str, float]] = {}

    class _Adapter:
        async def hgetall(self, key: str) -> dict[str, str]:
            calls.append(("hgetall", key))
            return dict(hashes.get(key) or {})

        async def get(self, key: str) -> str | None:
            calls.append(("get", key))
            return strings.get(key)

        async def set(self, key: str, value: str) -> int:
            calls.append(("set", key, value))
            strings[key] = value
            return 1

        async def zadd(self, key: str, mapping: dict[str, float]) -> int:
            calls.append(("zadd", key, mapping))
            bucket = sorted_sets.setdefault(key, {})
            before = len(bucket)
            bucket.update(mapping)
            return len(bucket) - before

        async def zrevrange(self, key: str, start: int, end: int) -> list[str]:
            calls.append(("zrevrange", key, start, end))
            values = sorted(
                sorted_sets.get(key, {}).items(),
                key=lambda item: item[1],
                reverse=True,
            )
            if end < 0:
                sliced = values[start:]
            else:
                sliced = values[start : end + 1]
            return [item[0] for item in sliced]

        async def eval(self, script: str, numkeys: int, *keys_and_args):
            calls.append(("eval", script, numkeys, *keys_and_args))
            key = str(keys_and_args[0])
            if "status', 'started'" in script:
                idem_key = str(keys_and_args[1])
                hashes[key] = {
                    "response_id": str(keys_and_args[2]),
                    "agent_id": str(keys_and_args[3]),
                    "session_key": str(keys_and_args[4]),
                    "stream": str(keys_and_args[5]),
                    "idempotency_key": str(keys_and_args[6]),
                    "status": "started",
                    "effective_status": "in_progress",
                    "created_at_ms": str(keys_and_args[7]),
                    "updated_at_ms": str(keys_and_args[7]),
                }
                if str(keys_and_args[6]):
                    strings[idem_key] = str(keys_and_args[2])
                return 1
            if "'status', 'aborted'" in script:
                if key not in hashes or hashes[key].get("ended_at_ms"):
                    return 0
                hashes[key]["status"] = "aborted"
                hashes[key]["effective_status"] = "cancelled"
                hashes[key]["updated_at_ms"] = str(keys_and_args[1])
                return 1
            if key not in hashes:
                return 0
            hashes[key]["status"] = str(keys_and_args[1])
            hashes[key]["effective_status"] = str(keys_and_args[2])
            hashes[key]["updated_at_ms"] = str(keys_and_args[3])
            hashes[key]["ended_at_ms"] = str(keys_and_args[3])
            hashes[key]["final_response_json"] = str(keys_and_args[4])
            hashes[key]["error_json"] = str(keys_and_args[5])
            return 1

        async def pexpire(self, key: str, time_ms: int) -> int:
            calls.append(("pexpire", key, time_ms))
            return 1

    store = RedisRunStore(
        redis_dsn="redis://localhost:6379/0",
        namespace="demo",
        adapter=_Adapter(),
    )
    run_key = build_redis_run_store_key(namespace="demo", response_id="resp_1")
    idem_key = build_redis_run_store_idempotency_key(namespace="demo", idempotency_key="idem-1")
    started = await store.create_started(
        response_id="resp_1",
        agent_id="main",
        session_key="sess-1",
        stream=False,
        idempotency_key="idem-1",
    )
    assert started.response_id == "resp_1"
    got = await store.get("resp_1")
    assert got is not None and got.status == "started"
    got_by_idem = await store.get_by_idempotency_key("idem-1")
    assert got_by_idem is not None and got_by_idem.response_id == "resp_1"
    await store.mark_cancel_requested("resp_1")
    cancelled = await store.get("resp_1")
    assert cancelled is not None and cancelled.effective_status == "cancelled"
    await store.mark_final(
        response_id="resp_1",
        status="completed",
        effective_status="completed",
        final_response_json={"id": "resp_1", "status": "completed"},
    )
    final = await store.get("resp_1")
    assert final is not None and final.ended_at_ms is not None
    assert strings[idem_key] == "resp_1"
    assert run_key in hashes
    assert any(call[0] == "pexpire" and call[1] == run_key for call in calls)
    assert any(call[0] == "pexpire" and call[1] == idem_key for call in calls)


def test_redis_event_store_roundtrip_via_adapter() -> None:
    asyncio.run(_run_redis_event_store_roundtrip_via_adapter())


async def _run_redis_event_store_roundtrip_via_adapter() -> None:
    calls: list[tuple] = []
    hashes: dict[str, dict[str, str]] = {}
    lists: dict[str, list[str]] = {}

    class _Adapter:
        async def hgetall(self, key: str) -> dict[str, str]:
            calls.append(("hgetall", key))
            return dict(hashes.get(key) or {})

        async def llen(self, key: str) -> int:
            calls.append(("llen", key))
            return len(lists.get(key) or [])

        async def lrange(self, key: str, start: int, stop: int) -> list[str]:
            calls.append(("lrange", key, start, stop))
            values = lists.get(key) or []
            if stop < 0:
                stop = len(values) - 1
            return values[start : stop + 1]

        async def eval(self, script: str, numkeys: int, *keys_and_args):
            calls.append(("eval", script, numkeys, *keys_and_args))
            meta_key = str(keys_and_args[0])
            if "HINCRBY" in script:
                list_key = str(keys_and_args[1])
                event = str(keys_and_args[2]) or None
                data = str(keys_and_args[3])
                meta = hashes.setdefault(meta_key, {})
                seq = int(meta.get("next_seq") or 0) + 1
                meta["next_seq"] = str(seq)
                meta.setdefault("done", "0")
                lists.setdefault(list_key, []).append(json.dumps({"seq": seq, "event": event, "data": data}, ensure_ascii=False))
                return seq
            if "'run_status', 'started'" in script:
                meta = hashes.setdefault(meta_key, {})
                meta["done"] = "0"
                meta["run_status"] = "started"
                meta["effective_run_status"] = "in_progress"
                meta.setdefault("next_seq", "0")
                return 1
            if "'run_status', 'aborted'" in script:
                meta = hashes.setdefault(meta_key, {})
                if meta.get("done") == "1":
                    return 0
                meta["run_status"] = "aborted"
                meta["effective_run_status"] = "cancelled"
                return 1
            meta = hashes.setdefault(meta_key, {})
            meta["done"] = "1"
            meta["run_status"] = str(keys_and_args[1])
            meta["effective_run_status"] = str(keys_and_args[2])
            meta["response_json"] = str(keys_and_args[3])
            meta["error"] = str(keys_and_args[4])
            meta.setdefault("next_seq", "0")
            return 1

        async def pexpire(self, key: str, time_ms: int) -> int:
            calls.append(("pexpire", key, time_ms))
            return 1

    store = RedisEventStore(
        redis_dsn="redis://localhost:6379/0",
        namespace="demo",
        adapter=_Adapter(),
        poll_interval_s=0.01,
    )
    meta_key = build_redis_event_meta_key(namespace="demo", response_id="resp_event_1")
    list_key = build_redis_event_list_key(namespace="demo", response_id="resp_event_1")
    await store.mark_started(response_id="resp_event_1")
    seq1 = await store.append(response_id="resp_event_1", event="response.created", data='{"id":"resp_event_1"}')
    seq2 = await store.append(response_id="resp_event_1", event="response.completed", data='{"id":"resp_event_1","status":"completed"}')
    assert (seq1, seq2) == (1, 2)
    await store.mark_final(
        response_id="resp_event_1",
        run_status="completed",
        effective_run_status="completed",
        response_json={"id": "resp_event_1", "status": "completed"},
    )
    listed = await store.list_events(response_id="resp_event_1", last_seq=0, limit=10)
    assert listed.next_last_seq == 2
    assert [item.event for item in listed.events] == ["response.created", "response.completed"]
    latest_seq = await store.latest_seq("resp_event_1")
    assert latest_seq == 2
    response_json = await store.get_response("resp_event_1")
    assert response_json == {"id": "resp_event_1", "status": "completed"}
    status, error = await store.get_status("resp_event_1")
    assert status == "completed"
    assert error is None
    streamed = []
    async for item in store.stream_events(response_id="resp_event_1", last_seq=0):
        streamed.append(item.event)
    assert streamed == ["response.created", "response.completed"]
    assert meta_key in hashes and list_key in lists
    assert any(call[0] == "pexpire" and call[1] == meta_key for call in calls)
    assert any(call[0] == "pexpire" and call[1] == list_key for call in calls)


def test_session_lock_service_rejects_conflicting_owner_and_renews() -> None:
    asyncio.run(_run_session_lock_service_rejects_conflicting_owner_and_renews())


async def _run_session_lock_service_rejects_conflicting_owner_and_renews() -> None:
    service = InMemorySessionLockService()
    async with hold_session_lease(
        service=service,
        session_partition_key="main::sess-lease",
        owner_id="run:1",
        ttl_s=0.09,
    ):
        current1 = await service.get(session_partition_key="main::sess-lease")
        assert current1 is not None
        await asyncio.sleep(0.14)
        current2 = await service.get(session_partition_key="main::sess-lease")
        assert current2 is not None
        assert current2.owner_id == "run:1"
        assert current2.expires_at_ms >= current1.expires_at_ms
        try:
            await service.acquire(
                session_partition_key="main::sess-lease",
                owner_id="run:2",
                ttl_s=0.09,
            )
        except SessionLeaseConflict as exc:
            assert exc.current_owner_id == "run:1"
        else:
            raise RuntimeError("expected SessionLeaseConflict")
    assert await service.get(session_partition_key="main::sess-lease") is None


def test_external_session_lock_service_delegates_to_backend_client() -> None:
    asyncio.run(_run_external_session_lock_service_delegates_to_backend_client())


async def _run_external_session_lock_service_delegates_to_backend_client() -> None:
    calls: list[tuple[str, str, str, float | None]] = []

    class _BackendClient:
        async def get_lease(self, *, session_partition_key: str) -> SessionLeaseRecord | None:
            calls.append(("get", session_partition_key, "", None))
            return SessionLeaseRecord(
                session_partition_key=session_partition_key,
                owner_id="run:backend",
                expires_at_ms=123,
            )

        async def acquire_lease(self, *, session_partition_key: str, owner_id: str, ttl_s: float) -> SessionLeaseRecord:
            calls.append(("acquire", session_partition_key, owner_id, ttl_s))
            return SessionLeaseRecord(
                session_partition_key=session_partition_key,
                owner_id=owner_id,
                expires_at_ms=456,
            )

        async def renew_lease(self, *, session_partition_key: str, owner_id: str, ttl_s: float) -> SessionLeaseRecord:
            calls.append(("renew", session_partition_key, owner_id, ttl_s))
            return SessionLeaseRecord(
                session_partition_key=session_partition_key,
                owner_id=owner_id,
                expires_at_ms=789,
            )

        async def release_lease(self, *, session_partition_key: str, owner_id: str) -> None:
            calls.append(("release", session_partition_key, owner_id, None))

    service = ExternalSessionLockService(client=_BackendClient())
    lease = await service.get(session_partition_key="main::sess-external")
    assert lease is not None and lease.owner_id == "run:backend"
    await service.acquire(session_partition_key="main::sess-external", owner_id="run:1", ttl_s=3.0)
    await service.renew(session_partition_key="main::sess-external", owner_id="run:1", ttl_s=3.0)
    await service.release(session_partition_key="main::sess-external", owner_id="run:1")
    assert calls == [
        ("get", "main::sess-external", "", None),
        ("acquire", "main::sess-external", "run:1", 3.0),
        ("renew", "main::sess-external", "run:1", 3.0),
        ("release", "main::sess-external", "run:1", None),
    ]


def test_build_session_lock_service_external_without_backend_raises_clear_error() -> None:
    asyncio.run(_run_build_session_lock_service_external_without_backend_raises_clear_error())


async def _run_build_session_lock_service_external_without_backend_raises_clear_error() -> None:
    service = build_session_lock_service(backend="external")
    try:
        await service.acquire(session_partition_key="main::sess-external-missing", owner_id="run:1", ttl_s=3.0)
    except RuntimeError as exc:
        assert "session lock backend not configured" in str(exc)
    else:
        raise RuntimeError("expected RuntimeError")


def test_build_session_lock_service_redis_without_dsn_raises_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_DSN", raising=False)
    try:
        build_session_lock_service(backend="redis")
    except RuntimeError as exc:
        assert "REDIS_DSN" in str(exc)
    else:
        raise RuntimeError("expected RuntimeError")


def test_server_settings_storage_mode_external_resolves_external_defaults() -> None:
    settings = ServerSettings(
        STORAGE_MODE="external",
        SESSION_LEASE_TTL_S=12.5,
    )
    resolved = settings.resolve()
    assert resolved.storage_mode == "external"
    assert resolved.event_store_backend == "external"
    assert resolved.run_store_backend == "external"
    assert resolved.session_store_backend == "external"
    assert resolved.session_lock_backend == "redis"
    assert resolved.session_lease_ttl_s == 12.5


def test_create_app_storage_mode_external_with_store_overrides_uses_redis_lock(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("STORAGE_MODE", "external")
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="inmemory",
        session_store_backend="inmemory",
    )
    assert isinstance(app.state.anyagent.events, InMemoryEventStore)
    assert isinstance(app.state.anyagent.run_store, InMemoryRunStore)
    assert isinstance(app.state.anyagent.session_store, InMemorySessionStore)
    assert isinstance(app.state.anyagent.session_lock_service, ExternalSessionLockService)


def test_create_app_uses_redis_event_store_backend_from_env(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="external",
        run_store_backend="inmemory",
        session_store_backend="inmemory",
    )
    assert isinstance(app.state.anyagent.events, RedisEventStore)


def test_create_app_uses_cached_run_store_when_postgres_available(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="external",
        session_store_backend="inmemory",
    )
    assert isinstance(app.state.anyagent.run_store, CachedRunStore)


def test_create_app_uses_cached_event_store_when_postgres_available(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="external",
        run_store_backend="inmemory",
        session_store_backend="inmemory",
    )
    assert isinstance(app.state.anyagent.events, CachedEventStore)


def test_create_app_uses_redis_session_store_backend_from_env(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="inmemory",
        session_store_backend="external",
    )
    assert isinstance(app.state.anyagent.session_store, RedisSessionStore)


def test_create_app_uses_cached_session_store_when_postgres_available(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="inmemory",
        session_store_backend="external",
    )
    assert isinstance(app.state.anyagent.session_store, CachedSessionStore)


def test_create_app_uses_redis_run_store_backend_from_env(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="external",
        session_store_backend="inmemory",
    )
    assert isinstance(app.state.anyagent.run_store, RedisRunStore)


def test_create_app_storage_mode_external_without_store_overrides_uses_redis_backends(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("STORAGE_MODE", "external")
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    assert isinstance(app.state.anyagent.events, CachedEventStore)
    assert isinstance(app.state.anyagent.run_store, CachedRunStore)
    assert isinstance(app.state.anyagent.session_store, CachedSessionStore)
    assert isinstance(app.state.anyagent.session_lock_service, ExternalSessionLockService)


def test_redis_session_lock_key_uses_namespace() -> None:
    assert build_redis_session_lock_key(namespace="demo", session_partition_key="main::sess-1") == "demo:lease:main::sess-1"


def test_redis_session_lock_client_acquire_renew_release_via_adapter() -> None:
    asyncio.run(_run_redis_session_lock_client_acquire_renew_release_via_adapter())


async def _run_redis_session_lock_client_acquire_renew_release_via_adapter() -> None:
    calls: list[tuple] = []
    state: dict[str, tuple[str, int]] = {}

    class _Adapter:
        async def get(self, key: str) -> str | None:
            calls.append(("get", key))
            value = state.get(key)
            return None if value is None else value[0]

        async def pttl(self, key: str) -> int:
            calls.append(("pttl", key))
            value = state.get(key)
            return -2 if value is None else value[1]

        async def set(self, key: str, value: str, *, nx: bool = False, px: int | None = None) -> bool | None:
            calls.append(("set", key, value, nx, px))
            if nx and key in state:
                return False
            state[key] = (value, int(px or 0))
            return True

        async def eval(self, script: str, numkeys: int, *keys_and_args):
            calls.append(("eval", script, numkeys, *keys_and_args))
            key = str(keys_and_args[0])
            owner = str(keys_and_args[1])
            if "PEXPIRE" in script:
                ttl_ms = int(keys_and_args[2])
                current = state.get(key)
                if current is None or current[0] != owner:
                    return 0
                state[key] = (owner, ttl_ms)
                return 1
            current = state.get(key)
            if current is None or current[0] != owner:
                return 0
            del state[key]
            return 1

    client = RedisSessionLockClient(
        redis_dsn="redis://localhost:6379/0",
        namespace="demo",
        adapter=_Adapter(),
    )
    key = "demo:lease:main::sess-redis"
    acquired = await client.acquire_lease(
        session_partition_key="main::sess-redis",
        owner_id="run:1",
        ttl_s=3.0,
    )
    assert acquired.owner_id == "run:1"
    current = await client.get_lease(session_partition_key="main::sess-redis")
    assert current is not None and current.owner_id == "run:1"
    renewed = await client.renew_lease(
        session_partition_key="main::sess-redis",
        owner_id="run:1",
        ttl_s=5.0,
    )
    assert renewed.owner_id == "run:1"
    await client.release_lease(session_partition_key="main::sess-redis", owner_id="run:1")
    assert state == {}
    assert calls[0] == ("set", key, "run:1", True, 3000)
    assert calls[1] == ("get", key)
    assert calls[2] == ("pttl", key)
    assert calls[3][0] == "eval" and calls[3][2] == 1 and calls[3][3] == key
    assert calls[4][0] == "eval" and calls[4][2] == 1 and calls[4][3] == key


def test_create_app_uses_redis_session_lock_backend_from_env(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("SESSION_LOCK_BACKEND", "redis")
    monkeypatch.setenv("REDIS_DSN", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("REDIS_NAMESPACE", "demo")
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    service = app.state.anyagent.session_lock_service
    assert isinstance(service, ExternalSessionLockService)
    client = service._client
    assert isinstance(client, RedisSessionLockClient)
    assert client._namespace == "demo"


def test_session_redis_lease_active_during_inflight_request_live(tmp_path: Path, monkeypatch) -> None:
    redis_dsn = os.getenv("ANYAGENT_TEST_REDIS_DSN")
    if not redis_dsn or not redis_dsn.strip():
        pytest.skip("ANYAGENT_TEST_REDIS_DSN not set")
    asyncio.run(
        _run_session_redis_lease_active_during_inflight_request_live(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            redis_dsn=redis_dsn.strip(),
        )
    )


async def _run_session_redis_lease_active_during_inflight_request_live(
    *,
    tmp_path: Path,
    monkeypatch,
    redis_dsn: str,
) -> None:
    _write_workspace(tmp_path)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    namespace = f"anyagent-live-{int(time.time() * 1000)}"

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = body, idempotency_key, timeout_s
            first_started.set()
            await release_first.wait()
            payload = {
                "id": "resp_record_redis_live_1",
                "object": "response",
                "created_at": int(time.time()),
                "model": "gpt-4o-mini",
                "output": [
                    ResponseOutputMessage(
                        id="msg_redis_live_1",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setenv("SESSION_LOCK_BACKEND", "redis")
    monkeypatch.setenv("REDIS_DSN", redis_dsn)
    monkeypatch.setenv("REDIS_NAMESPACE", namespace)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    session_key = "sess-session-redis-live"
    spk = f"main::{session_key}"
    redis_key = build_redis_session_lock_key(namespace=namespace, session_partition_key=spk)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        task = asyncio.create_task(
            client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer user-key"},
                json={"input": "hello", "metadata": {"session_key": session_key}},
            )
        )
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        lease = await app.state.anyagent.session_lock_service.get(session_partition_key=spk)
        assert lease is not None
        assert lease.owner_id.startswith("run:resp_")
        assert build_redis_session_lock_key(namespace=namespace, session_partition_key=spk) == redis_key
        release_first.set()
        resp = await task
        assert resp.status_code == 200
        assert await app.state.anyagent.session_lock_service.get(session_partition_key=spk) is None


def test_session_redis_session_store_roundtrip_live(tmp_path: Path, monkeypatch) -> None:
    redis_dsn = os.getenv("ANYAGENT_TEST_REDIS_DSN")
    if not redis_dsn or not redis_dsn.strip():
        pytest.skip("ANYAGENT_TEST_REDIS_DSN not set")
    asyncio.run(
        _run_session_redis_session_store_roundtrip_live(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            redis_dsn=redis_dsn.strip(),
        )
    )


async def _run_session_redis_session_store_roundtrip_live(
    *,
    tmp_path: Path,
    monkeypatch,
    redis_dsn: str,
) -> None:
    _write_workspace(tmp_path)
    seen_bodies: list[dict] = []
    namespace = f"anyagent-session-live-{int(time.time() * 1000)}"

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = idempotency_key, timeout_s
            seen_bodies.append(json.loads(json.dumps(body)))
            payload = {
                "id": f"resp_record_session_live_{len(seen_bodies)}",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id=f"msg_session_live_{len(seen_bodies)}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setenv("REDIS_DSN", redis_dsn)
    monkeypatch.setenv("REDIS_NAMESPACE", namespace)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="inmemory",
        session_store_backend="external",
        session_lock_backend="redis",
    )
    assert isinstance(app.state.anyagent.session_store, RedisSessionStore)
    transport = httpx.ASGITransport(app=app)
    session_key = "sess-session-redis-store-live"
    spk = f"main::{session_key}"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": session_key}},
        )
        assert resp1.status_code == 200
        stored = await app.state.anyagent.session_store.get(session_partition_key=spk)
        assert stored is not None
        assert stored.snapshot_json["resume_cursor"]["last_response_id"] == resp1.json()["id"]
        resp2 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"input": "follow up", "metadata": {"session_key": session_key}},
        )
        assert resp2.status_code == 200
        assert len(seen_bodies) == 2
        assert seen_bodies[1]["previous_response_id"] == resp1.json()["id"]


def test_session_cached_store_pg_primary_redis_hot_roundtrip_live(tmp_path: Path, monkeypatch) -> None:
    redis_dsn = os.getenv("ANYAGENT_TEST_REDIS_DSN")
    postgres_dsn = os.getenv("ANYAGENT_TEST_POSTGRES_DSN")
    if not redis_dsn or not redis_dsn.strip() or not postgres_dsn or not postgres_dsn.strip():
        pytest.skip("ANYAGENT_TEST_REDIS_DSN / ANYAGENT_TEST_POSTGRES_DSN not set")
    asyncio.run(
        _run_session_cached_store_pg_primary_redis_hot_roundtrip_live(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            redis_dsn=redis_dsn.strip(),
            postgres_dsn=postgres_dsn.strip(),
        )
    )


async def _run_session_cached_store_pg_primary_redis_hot_roundtrip_live(
    *,
    tmp_path: Path,
    monkeypatch,
    redis_dsn: str,
    postgres_dsn: str,
) -> None:
    _write_workspace(tmp_path)
    seen_bodies: list[dict] = []
    namespace = f"anyagent-pg-primary-{int(time.time() * 1000)}"

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = idempotency_key, timeout_s
            seen_bodies.append(json.loads(json.dumps(body)))
            payload = {
                "id": f"resp_record_pg_primary_{len(seen_bodies)}",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id=f"msg_pg_primary_{len(seen_bodies)}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setenv("REDIS_DSN", redis_dsn)
    _prepare_live_postgres_schema(monkeypatch=monkeypatch, postgres_dsn=postgres_dsn)
    monkeypatch.setenv("REDIS_NAMESPACE", namespace)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())

    app1 = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="inmemory",
        session_store_backend="external",
        session_lock_backend="redis",
    )
    assert isinstance(app1.state.anyagent.session_store, CachedSessionStore)
    transport1 = httpx.ASGITransport(app=app1)
    session_key = "sess-pg-primary-live"
    spk = f"main::{session_key}"
    async with httpx.AsyncClient(transport=transport1, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": session_key}},
        )
        assert resp1.status_code == 200

    cached_store1 = app1.state.anyagent.session_store
    redis_cache = cached_store1._cache
    redis_key = build_redis_session_store_key(namespace=namespace, session_partition_key=spk)
    from redis import asyncio as redis_asyncio

    redis = redis_asyncio.from_url(redis_dsn, encoding="utf-8", decode_responses=True)
    try:
        await redis.delete(redis_key)
    finally:
        await redis.aclose()

    app2 = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="inmemory",
        session_store_backend="external",
        session_lock_backend="redis",
    )
    transport2 = httpx.ASGITransport(app=app2)
    async with httpx.AsyncClient(transport=transport2, base_url="http://testserver", timeout=5.0) as client:
        resp2 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"input": "follow up", "metadata": {"session_key": session_key}},
        )
        assert resp2.status_code == 200
    assert len(seen_bodies) == 2
    assert seen_bodies[1]["previous_response_id"] == resp1.json()["id"]

    redis = redis_asyncio.from_url(redis_dsn, encoding="utf-8", decode_responses=True)
    try:
        cached_hash = await redis.hgetall(redis_key)
        assert cached_hash
    finally:
        await redis.aclose()


def test_pg_redis_session_run_event_replay_contract_live(tmp_path: Path, monkeypatch) -> None:
    redis_dsn = os.getenv("ANYAGENT_TEST_REDIS_DSN")
    postgres_dsn = os.getenv("ANYAGENT_TEST_POSTGRES_DSN")
    if not redis_dsn or not redis_dsn.strip() or not postgres_dsn or not postgres_dsn.strip():
        pytest.skip("ANYAGENT_TEST_REDIS_DSN / ANYAGENT_TEST_POSTGRES_DSN not set")
    asyncio.run(
        _run_pg_redis_session_run_event_replay_contract_live(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            redis_dsn=redis_dsn.strip(),
            postgres_dsn=postgres_dsn.strip(),
        )
    )


async def _run_pg_redis_session_run_event_replay_contract_live(
    *,
    tmp_path: Path,
    monkeypatch,
    redis_dsn: str,
    postgres_dsn: str,
) -> None:
    _write_workspace(tmp_path)
    seen_bodies: list[dict] = []
    namespace = f"anyagent-pg-redis-replay-{int(time.time() * 1000)}"

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = timeout_s
            seen_bodies.append({"body": json.loads(json.dumps(body)), "idempotency_key": idempotency_key})
            payload = {
                "id": f"resp_record_pg_redis_{len(seen_bodies)}",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id=f"msg_pg_redis_{len(seen_bodies)}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setenv("REDIS_DSN", redis_dsn)
    _prepare_live_postgres_schema(monkeypatch=monkeypatch, postgres_dsn=postgres_dsn)
    monkeypatch.setenv("REDIS_NAMESPACE", namespace)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())

    app1 = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="external",
        run_store_backend="external",
        session_store_backend="external",
        session_lock_backend="redis",
    )
    assert isinstance(app1.state.anyagent.events, CachedEventStore)
    assert isinstance(app1.state.anyagent.run_store, CachedRunStore)
    assert isinstance(app1.state.anyagent.session_store, CachedSessionStore)

    session_key = "sess-pg-redis-replay-live"
    idempotency_key = f"idem-pg-redis-{int(time.time() * 1000)}"
    transport1 = httpx.ASGITransport(app=app1)
    async with httpx.AsyncClient(transport=transport1, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key", "Idempotency-Key": idempotency_key},
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": session_key}},
        )
        assert resp1.status_code == 200
        response_id = resp1.json()["id"]

    app2 = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="external",
        run_store_backend="external",
        session_store_backend="external",
        session_lock_backend="redis",
    )
    assert isinstance(app2.state.anyagent.events, CachedEventStore)
    assert isinstance(app2.state.anyagent.run_store, CachedRunStore)
    assert isinstance(app2.state.anyagent.session_store, CachedSessionStore)

    run = await app2.state.anyagent.run_store.get(response_id)
    assert run is not None
    assert run.status == "completed"
    assert run.final_response_json is not None and run.final_response_json["id"] == response_id
    by_idempotency = await app2.state.anyagent.run_store.get_by_idempotency_key(idempotency_key)
    assert by_idempotency is not None and by_idempotency.response_id == response_id

    session = await app2.state.anyagent.session_store.get(session_partition_key=f"main::{session_key}")
    assert session is not None
    assert session.snapshot_json["resume_cursor"]["last_response_id"] == response_id

    listed = await app2.state.anyagent.events.list_events(response_id=response_id, last_seq=0, limit=50)
    event_names = [item.event for item in listed.events]
    assert "anyagent.prompt.context" in event_names
    assert "response.completed" in event_names
    assert listed.done is True

    transport2 = httpx.ASGITransport(app=app2)
    async with httpx.AsyncClient(transport=transport2, base_url="http://testserver", timeout=5.0) as client:
        replay = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key", "Idempotency-Key": idempotency_key},
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": session_key}},
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == response_id

    assert len(seen_bodies) == 1


def test_event_store_redis_roundtrip_live(tmp_path: Path, monkeypatch) -> None:
    redis_dsn = os.getenv("ANYAGENT_TEST_REDIS_DSN")
    if not redis_dsn or not redis_dsn.strip():
        pytest.skip("ANYAGENT_TEST_REDIS_DSN not set")
    asyncio.run(
        _run_event_store_redis_roundtrip_live(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            redis_dsn=redis_dsn.strip(),
        )
    )


async def _run_event_store_redis_roundtrip_live(
    *,
    tmp_path: Path,
    monkeypatch,
    redis_dsn: str,
) -> None:
    _write_workspace(tmp_path)
    namespace = f"anyagent-event-live-{int(time.time() * 1000)}"

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = body, idempotency_key, timeout_s
            payload = {
                "id": "resp_record_event_live_1",
                "object": "response",
                "created_at": int(time.time()),
                "model": "gpt-4o-mini",
                "output": [
                    ResponseOutputMessage(
                        id="msg_event_live_1",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setenv("REDIS_DSN", redis_dsn)
    postgres_dsn = os.getenv("ANYAGENT_TEST_POSTGRES_DSN")
    if postgres_dsn and postgres_dsn.strip():
        _prepare_live_postgres_schema(monkeypatch=monkeypatch, postgres_dsn=postgres_dsn.strip())
    monkeypatch.setenv("REDIS_NAMESPACE", namespace)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())

    app1 = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="external",
        run_store_backend="inmemory",
        session_store_backend="inmemory",
        session_lock_backend="redis",
    )
    if postgres_dsn and postgres_dsn.strip():
        assert isinstance(app1.state.anyagent.events, CachedEventStore)
    transport1 = httpx.ASGITransport(app=app1)
    async with httpx.AsyncClient(transport=transport1, base_url="http://testserver", timeout=5.0) as client:
        resp = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": "sess-event-live"}},
        )
        assert resp.status_code == 200
        response_id = resp.json()["id"]

    app2 = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="external",
        run_store_backend="inmemory",
        session_store_backend="inmemory",
    )
    if postgres_dsn and postgres_dsn.strip():
        assert isinstance(app2.state.anyagent.events, CachedEventStore)
    listed = await app2.state.anyagent.events.list_events(response_id=response_id, last_seq=0, limit=50)
    names = [item.event for item in listed.events]
    assert "response.completed" in names
    payload = await app2.state.anyagent.events.get_response(response_id)
    assert payload is not None and payload["id"] == response_id


def test_redis_store_ttl_policy_live(tmp_path: Path, monkeypatch) -> None:
    redis_dsn = os.getenv("ANYAGENT_TEST_REDIS_DSN")
    if not redis_dsn or not redis_dsn.strip():
        pytest.skip("ANYAGENT_TEST_REDIS_DSN not set")
    asyncio.run(
        _run_redis_store_ttl_policy_live(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            redis_dsn=redis_dsn.strip(),
        )
    )


async def _run_redis_store_ttl_policy_live(
    *,
    tmp_path: Path,
    monkeypatch,
    redis_dsn: str,
) -> None:
    _write_workspace(tmp_path)
    namespace = f"anyagent-ttl-live-{int(time.time() * 1000)}"

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = body, idempotency_key, timeout_s
            payload = {
                "id": "resp_record_ttl_live_1",
                "object": "response",
                "created_at": int(time.time()),
                "model": "gpt-4o-mini",
                "output": [
                    ResponseOutputMessage(
                        id="msg_ttl_live_1",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setenv("REDIS_DSN", redis_dsn)
    monkeypatch.setenv("REDIS_NAMESPACE", namespace)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        storage_mode="external",
    )
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer user-key", "Idempotency-Key": "idem-ttl-live-1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp = await client.post(
            "/v1/responses",
            headers=headers,
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": "sess-ttl-live"}},
        )
        assert resp.status_code == 200
        response_id = resp.json()["id"]

    from redis import asyncio as redis_asyncio

    redis = redis_asyncio.from_url(redis_dsn, encoding="utf-8", decode_responses=True)
    try:
        event_meta_ttl = await redis.pttl(build_redis_event_meta_key(namespace=namespace, response_id=response_id))
        event_list_ttl = await redis.pttl(build_redis_event_list_key(namespace=namespace, response_id=response_id))
        run_ttl = await redis.pttl(build_redis_run_store_key(namespace=namespace, response_id=response_id))
        run_idem_ttl = await redis.pttl(
            build_redis_run_store_idempotency_key(namespace=namespace, idempotency_key="idem-ttl-live-1")
        )
        session_ttl = await redis.pttl(
            build_redis_session_store_key(namespace=namespace, session_partition_key="main::sess-ttl-live")
        )
        assert 0 < event_meta_ttl <= 2 * 60 * 60 * 1000
        assert 0 < event_list_ttl <= 2 * 60 * 60 * 1000
        assert 0 < run_ttl <= 2 * 60 * 60 * 1000
        assert 0 < run_idem_ttl <= 2 * 60 * 60 * 1000
        assert 0 < session_ttl <= 24 * 60 * 60 * 1000
        assert session_ttl > run_ttl
    finally:
        await redis.aclose()


def test_run_store_redis_idempotency_roundtrip_live(tmp_path: Path, monkeypatch) -> None:
    redis_dsn = os.getenv("ANYAGENT_TEST_REDIS_DSN")
    if not redis_dsn or not redis_dsn.strip():
        pytest.skip("ANYAGENT_TEST_REDIS_DSN not set")
    asyncio.run(
        _run_run_store_redis_idempotency_roundtrip_live(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            redis_dsn=redis_dsn.strip(),
        )
    )


async def _run_run_store_redis_idempotency_roundtrip_live(
    *,
    tmp_path: Path,
    monkeypatch,
    redis_dsn: str,
) -> None:
    _write_workspace(tmp_path)
    call_count = {"n": 0}
    namespace = f"anyagent-run-live-{int(time.time() * 1000)}"
    idempotency_key = f"idem-run-live-{int(time.time() * 1000)}"

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = body, idempotency_key, timeout_s
            call_count["n"] += 1
            payload = {
                "id": f"resp_record_run_live_{call_count['n']}",
                "object": "response",
                "created_at": int(time.time()),
                "model": "gpt-4o-mini",
                "output": [
                    ResponseOutputMessage(
                        id=f"msg_run_live_{call_count['n']}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setenv("REDIS_DSN", redis_dsn)
    postgres_dsn = os.getenv("ANYAGENT_TEST_POSTGRES_DSN")
    if postgres_dsn and postgres_dsn.strip():
        _prepare_live_postgres_schema(monkeypatch=monkeypatch, postgres_dsn=postgres_dsn.strip())
    monkeypatch.setenv("REDIS_NAMESPACE", namespace)
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())

    app1 = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="external",
        session_store_backend="inmemory",
        session_lock_backend="redis",
    )
    if postgres_dsn and postgres_dsn.strip():
        assert isinstance(app1.state.anyagent.run_store, CachedRunStore)
    transport1 = httpx.ASGITransport(app=app1)
    headers = {"Authorization": "Bearer user-key", "Idempotency-Key": idempotency_key}
    async with httpx.AsyncClient(transport=transport1, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post(
            "/v1/responses",
            headers=headers,
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": "sess-run-live"}},
        )
        assert resp1.status_code == 200
    assert call_count["n"] == 1

    app2 = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
        event_store_backend="inmemory",
        run_store_backend="external",
        session_store_backend="inmemory",
        session_lock_backend="redis",
    )
    if postgres_dsn and postgres_dsn.strip():
        assert isinstance(app2.state.anyagent.run_store, CachedRunStore)
    transport2 = httpx.ASGITransport(app=app2)
    async with httpx.AsyncClient(transport=transport2, base_url="http://testserver", timeout=5.0) as client:
        resp2 = await client.post(
            "/v1/responses",
            headers=headers,
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": "sess-run-live"}},
        )
        assert resp2.status_code == 200
        assert resp2.json()["id"] == resp1.json()["id"]
    assert call_count["n"] == 1


def test_session_fallback_transcript_items_used_when_last_response_id_missing(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_session_fallback_transcript_items_used_when_last_response_id_missing(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_session_fallback_transcript_items_used_when_last_response_id_missing(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    seen_bodies: list[dict] = []

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = idempotency_key, timeout_s
            seen_bodies.append(json.loads(json.dumps(body)))
            payload = {
                "id": f"resp_record_fallback_{len(seen_bodies)}",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id=f"msg_fallback_{len(seen_bodies)}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        resp1 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"model": "gpt-4o-mini", "input": "hello", "metadata": {"session_key": "sess-session-fallback"}},
        )
        assert resp1.status_code == 200

        session_record = await app.state.anyagent.session_store.get(session_partition_key="main::sess-session-fallback")
        assert session_record is not None
        resume_cursor = session_record.snapshot_json["resume_cursor"]
        assert resume_cursor["last_response_id"] == resp1.json()["id"]
        assert resume_cursor["fallback_transcript_items"] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok"},
        ]

        mutated_snapshot = dict(session_record.snapshot_json)
        mutated_resume = dict(resume_cursor)
        mutated_resume["last_response_id"] = None
        mutated_snapshot["resume_cursor"] = mutated_resume
        await app.state.anyagent.session_store.upsert(
            session_partition_key="main::sess-session-fallback",
            agent_id="main",
            session_key="sess-session-fallback",
            snapshot_json=mutated_snapshot,
            expected_snapshot_version=session_record.snapshot_version,
        )

        resp2 = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"input": "follow up", "metadata": {"session_key": "sess-session-fallback"}},
        )
        assert resp2.status_code == 200
        assert len(seen_bodies) == 2, seen_bodies
        assert "previous_response_id" not in seen_bodies[1], seen_bodies[1]
        input_items = seen_bodies[1]["input"]
        assert isinstance(input_items, list), seen_bodies[1]
        convo = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in input_items
            if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
        ]
        assert convo == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "follow up"},
        ], seen_bodies[1]


def test_session_lease_active_during_inflight_request(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_session_lease_active_during_inflight_request(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_session_lease_active_during_inflight_request(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = body, idempotency_key, timeout_s
            first_started.set()
            await release_first.wait()
            payload = {
                "id": "resp_record_lease_1",
                "object": "response",
                "created_at": int(time.time()),
                "model": "gpt-4o-mini",
                "output": [
                    ResponseOutputMessage(
                        id="msg_lease_1",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        task = asyncio.create_task(
            client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer user-key"},
                json={"input": "hello", "metadata": {"session_key": "sess-session-lease"}},
            )
        )
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        lease = await app.state.anyagent.session_lock_service.get(session_partition_key="main::sess-session-lease")
        assert lease is not None
        assert lease.owner_id.startswith("run:resp_")
        release_first.set()
        resp = await task
        assert resp.status_code == 200
        assert await app.state.anyagent.session_lock_service.get(session_partition_key="main::sess-session-lease") is None


def test_session_concurrent_requests_are_serialized(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_session_concurrent_requests_are_serialized(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_session_concurrent_requests_are_serialized(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    seen_bodies: list[dict] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class _RecordingProvider:
        async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
            _ = idempotency_key, timeout_s
            seen_bodies.append(json.loads(json.dumps(body)))
            call_index = len(seen_bodies)
            if call_index == 1:
                first_started.set()
                await release_first.wait()
            payload = {
                "id": f"resp_record_serial_{call_index}",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id=f"msg_serial_{call_index}",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)

        async def create_response_stream_buffered(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float | None = None):
            resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
            return [
                ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp),
                ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp),
            ], resp

    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
        first_task = asyncio.create_task(
            client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer user-key"},
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0.2,
                    "input": "hello",
                    "metadata": {"session_key": "sess-session-serial"},
                },
            )
        )
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        second_task = asyncio.create_task(
            client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer user-key"},
                json={"input": "follow up", "metadata": {"session_key": "sess-session-serial"}},
            )
        )
        await asyncio.sleep(0.1)
        assert len(seen_bodies) == 1, seen_bodies
        release_first.set()
        resp1, resp2 = await asyncio.gather(first_task, second_task)
        payload1 = resp1.json()
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert len(seen_bodies) == 2, seen_bodies
        assert seen_bodies[1]["model"] == "gpt-4o-mini", seen_bodies[1]
        assert seen_bodies[1]["temperature"] == 0.2, seen_bodies[1]
        assert seen_bodies[1]["previous_response_id"] == payload1["id"], seen_bodies[1]
