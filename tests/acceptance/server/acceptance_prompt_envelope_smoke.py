from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.server.app import create_app


class _RecordingProvider:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        self.bodies.append(dict(body))
        payload = {
            "id": "resp_prompt_envelope",
            "object": "response",
            "created_at": int(time.time()),
            "model": str(body.get("model") or "gpt-4o-mini"),
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


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        """
exposed: true
tools:
  requested_tool_names: [exec]
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


def test_builtin_server_applies_prompt_envelope_to_provider_request(tmp_path: Path) -> None:
    asyncio.run(_run_builtin_server_applies_prompt_envelope_to_provider_request(tmp_path=tmp_path))


async def _run_builtin_server_applies_prompt_envelope_to_provider_request(*, tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    provider = _RecordingProvider()

    import anyagent.server.app as app_mod

    original = app_mod.get_default_model_provider
    app_mod.get_default_model_provider = lambda: provider
    try:
        app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            preview = await client.post(
                "/internal/prompt/bundle",
                headers={"Authorization": "Bearer user-key"},
                json={"model": "gpt-5", "input": "hello", "stream": False, "metadata": {"session_key": "sess_prompt"}},
            )
            assert preview.status_code == 200
            preview_payload = preview.json()
            assert "exec" in preview_payload["manifest_tool_names"]
            assert any(item["kind"] == "sandbox_guidance" for item in preview_payload["rendered_fragments"])
            assert any(
                "<sandbox_guidance>" in item["rendered_text"] for item in preview_payload["rendered_fragments"]
            )
            assert any(
                isinstance(item.get("content"), str) and "<sandbox_guidance>" in item["content"]
                for item in preview_payload["applied_body"]["input"]
                if isinstance(item, dict)
            )

            resp = await client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer user-key"},
                json={"model": "gpt-5", "input": "hello", "stream": False, "metadata": {"session_key": "sess_prompt"}},
            )
            assert resp.status_code == 200
            payload = resp.json()
            response_id = payload["id"]
            assert provider.bodies, "provider should receive at least one request body"
            body = provider.bodies[0]
            assert isinstance(body.get("prompt_cache_key"), str) and body["prompt_cache_key"]
            input_items = body["input"]
            assert input_items[0]["role"] == "developer"
            assert input_items[0]["content"].startswith("# AGENTS.md instructions for agent:main")
            assert any(
                item.get("role") == "developer" and isinstance(item.get("content"), str) and item["content"].startswith("<environment_context>")
                for item in input_items
                if isinstance(item, dict)
            )
            assert any(
                item.get("role") == "developer" and isinstance(item.get("content"), str) and item["content"].startswith("<sandbox_guidance>")
                for item in input_items
                if isinstance(item, dict)
            )
            events_resp = await client.get(
                "/internal/events/list",
                params={"response_id": response_id},
                headers={"Authorization": "Bearer user-key"},
            )
            events_resp.raise_for_status()
            event_payload = events_resp.json()
            prompt_events = [
                item
                for item in event_payload["events"]
                if isinstance(item, dict) and item.get("event") == "anyagent.prompt.context"
            ]
            assert len(prompt_events) == 1
            session_record = await app.state.anyagent.session_store.get(session_partition_key="main::sess_prompt")
            assert session_record is not None
            prompt_context = session_record.snapshot_json["last_run"]["prompt_context"]
            assert prompt_context["prompt_cache_key"] == body["prompt_cache_key"]
            assert any(fragment["kind"] == "environment_context" for fragment in prompt_context["fragments"])
    finally:
        app_mod.get_default_model_provider = original
