from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import httpx
from openai.types.responses.response import Response

from anyagent.plugins.builtin.chatwoot_connector.plugin import _extract_reply_and_handoff
from anyagent.protocol.sse import SSEBlockDecoder
from anyagent.server.app import create_app

_PROVIDER_MODULE = "scripted_reply_fixture"


def _write_workspace(root: Path, *, provider_classpaths: list[str]) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    runtime_block = (
        ["runtime:", "  scripted_reply_providers:", *[f"    - {cp}" for cp in provider_classpaths]]
        if provider_classpaths
        else []
    )
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
                *runtime_block,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / f"{_PROVIDER_MODULE}.py").write_text(
        textwrap.dedent(
            '''
            from anyagent.agent_runtime import BaseScriptedReplyProvider, ScriptedReplyRequest


            def _user_text(request: ScriptedReplyRequest) -> str:
                value = request.body.get("input")
                if isinstance(value, str):
                    return value
                if isinstance(value, list):
                    for item in reversed(value):
                        if isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("content"), str):
                            return item["content"]
                return ""


            class GreetingProvider(BaseScriptedReplyProvider):
                async def resolve(self, request: ScriptedReplyRequest):
                    if _user_text(request).strip().lower() == "hi":
                        return {"text": "Hello from script", "variant_id": "greeting-v1", "reason": "quick_prompt"}
                    return None


            class FirstTurnOnlyProvider(BaseScriptedReplyProvider):
                async def resolve(self, request: ScriptedReplyRequest):
                    if request.is_first_turn:
                        return {"text": "Welcome, first turn", "variant_id": "welcome"}
                    return None


            class Broken:
                pass
            '''
        ),
        encoding="utf-8",
    )
    sys.modules.pop(_PROVIDER_MODULE, None)


class _RecordingProvider:
    def __init__(self) -> None:
        self.seen_bodies: list[dict] = []

    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        self.seen_bodies.append(json.loads(json.dumps(body)))
        return Response.model_validate(
            {
                "id": f"resp_model_{len(self.seen_bodies)}",
                "object": "response",
                "created_at": 123,
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    {
                        "id": "msg_model",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "model answer", "annotations": []}],
                    }
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "status": "completed",
            }
        )


def _decode_sse(text: str) -> list[tuple[str | None, str]]:
    decoder = SSEBlockDecoder()
    blocks = []
    for line in text.splitlines():
        blocks.extend(decoder.feed_line(line))
    blocks.extend(decoder.flush())
    return [(blk.event, blk.data) for blk in blocks if not (blk.data.startswith(":"))]


def test_scripted_hit_skips_model_and_enters_next_turn_context(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_scripted_hit_skips_model_and_enters_next_turn_context(tmp_path, monkeypatch))


async def _run_scripted_hit_skips_model_and_enters_next_turn_context(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path, provider_classpaths=[f"{_PROVIDER_MODULE}:GreetingProvider"])
    provider = _RecordingProvider()
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: provider)

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent
    headers = {"Authorization": "Bearer user-key"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0) as http:
        first = await http.post(
            "/v1/responses",
            headers=headers,
            json={"model": "gpt-4o-mini", "input": [{"role": "user", "content": "hi"}], "metadata": {"session_key": "s1"}},
        )
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["status"] == "completed"
        assert payload["object"] == "response"
        reply_text, handoff = _extract_reply_and_handoff(payload)
        assert reply_text == "Hello from script"
        assert handoff is None
        assert provider.seen_bodies == []

        events = await state.events.list_events(response_id=payload["id"], last_seq=0, limit=100)
        by_type = [item.event for item in events.events]
        assert "anyagent.response.scripted" in by_type
        assert "anyagent.model.request" not in by_type
        assert by_type[-2:] == ["response.completed", None]
        scripted_row = next(item for item in events.events if item.event == "anyagent.response.scripted")
        scripted_payload = json.loads(scripted_row.data)
        assert scripted_payload["provider"] == "GreetingProvider"
        assert scripted_payload["variant_id"] == "greeting-v1"

        run = await state.run_store.get(payload["id"])
        assert run is not None and run.effective_status == "completed"

        second = await http.post(
            "/v1/responses",
            headers=headers,
            json={"input": [{"role": "user", "content": "tell me more"}], "metadata": {"session_key": "s1"}},
        )
        assert second.status_code == 200, second.text

    assert len(provider.seen_bodies) == 1, provider.seen_bodies
    model_input = provider.seen_bodies[0]["input"]
    assert isinstance(model_input, list)
    assert {"role": "assistant", "content": "Hello from script"} in model_input
    assert {"role": "user", "content": "hi"} in model_input
    assert model_input[-1] == {"role": "user", "content": "tell me more"}


def test_scripted_hit_streams_delta_completed_done(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_scripted_hit_streams_delta_completed_done(tmp_path, monkeypatch))


async def _run_scripted_hit_streams_delta_completed_done(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path, provider_classpaths=[f"{_PROVIDER_MODULE}:GreetingProvider"])
    provider = _RecordingProvider()
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: provider)

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0) as http:
        async with http.stream(
            "POST",
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"model": "gpt-4o-mini", "input": "hi", "stream": True, "metadata": {"session_key": "s-stream"}},
        ) as resp:
            assert resp.status_code == 200
            text = (await resp.aread()).decode("utf-8")

    blocks = _decode_sse(text)
    events = [event for event, _ in blocks]
    assert events[0] == "response.created"
    assert "response.output_text.delta" in events
    assert events[-2:] == ["response.completed", None]
    delta = json.loads(next(data for event, data in blocks if event == "response.output_text.delta"))
    assert delta["delta"] == "Hello from script"
    completed = json.loads(next(data for event, data in blocks if event == "response.completed"))
    response_id = completed["response"]["id"]
    assert provider.seen_bodies == []

    record = await state.session_store.get(session_partition_key="main::s-stream")
    assert record is not None
    assert record.snapshot_json["resume_cursor"]["last_response_id"] == response_id
    transcript = record.snapshot_json["resume_cursor"]["fallback_transcript_items"]
    assert {"role": "assistant", "content": "Hello from script"} in transcript


def test_scripted_miss_and_broken_provider_fall_through_to_model(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_scripted_miss_and_broken_provider_fall_through_to_model(tmp_path, monkeypatch))


async def _run_scripted_miss_and_broken_provider_fall_through_to_model(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(
        tmp_path,
        provider_classpaths=[f"{_PROVIDER_MODULE}:Broken", "missing_module:Nope", f"{_PROVIDER_MODULE}:GreetingProvider"],
    )
    provider = _RecordingProvider()
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: provider)

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0) as http:
        resp = await http.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"model": "gpt-4o-mini", "input": "not a greeting", "metadata": {"session_key": "s-miss"}},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()

    assert len(provider.seen_bodies) == 1
    reply_text, _ = _extract_reply_and_handoff(payload)
    assert reply_text == "model answer"
    events = await state.events.list_events(response_id=payload["id"], last_seq=0, limit=100)
    assert "anyagent.response.scripted" not in [item.event for item in events.events]
    assert "anyagent.model.request" in [item.event for item in events.events]


def test_first_turn_only_provider_sees_previous_transcript(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_first_turn_only_provider_sees_previous_transcript(tmp_path, monkeypatch))


async def _run_first_turn_only_provider_sees_previous_transcript(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path, provider_classpaths=[f"{_PROVIDER_MODULE}:FirstTurnOnlyProvider"])
    provider = _RecordingProvider()
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: provider)

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    headers = {"Authorization": "Bearer user-key"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0) as http:
        first = await http.post(
            "/v1/responses",
            headers=headers,
            json={"model": "gpt-4o-mini", "input": "anything", "metadata": {"session_key": "s-first"}},
        )
        assert first.status_code == 200, first.text
        assert _extract_reply_and_handoff(first.json())[0] == "Welcome, first turn"
        assert provider.seen_bodies == []

        second = await http.post(
            "/v1/responses",
            headers=headers,
            json={"input": "anything again", "metadata": {"session_key": "s-first"}},
        )
        assert second.status_code == 200, second.text
        assert _extract_reply_and_handoff(second.json())[0] == "model answer"

    assert len(provider.seen_bodies) == 1
