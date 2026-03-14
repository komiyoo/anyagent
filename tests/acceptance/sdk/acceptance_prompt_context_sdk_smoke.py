from __future__ import annotations

"""Offline smoke for SDK prompt-context replay helpers."""

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent import AnyAgent
import anyagent.server.app as server_app
from anyagent.server.app import create_app


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class _FakeProvider:
    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        payload = {
            "id": "resp_sdk_prompt_context",
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
  mode: local-unsafe
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


async def _main() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_workspace(root)
        original_provider = server_app.get_default_model_provider
        server_app.get_default_model_provider = lambda: _FakeProvider()
        try:
            app = create_app(
                workspace_dir=root,
                api_key="user-key",
                admin_api_key="admin-key",
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as http:
                create_resp = await http.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer user-key"},
                    json={"model": "gpt-4o-mini", "input": "run prompt context sdk smoke", "stream": False},
                )
                _assert(create_resp.status_code == 200, f"unexpected create status: {create_resp.status_code} {create_resp.text}")
                response_id = create_resp.json()["id"]

                client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
                listed = await client.events.list(response_id)
                typed_from_page = listed.typed_events(include_model_events=False)
                _assert(any(item.type == "anyagent.prompt.context" for item in typed_from_page), f"missing prompt context in typed page: {typed_from_page}")
                page_prompt_context = listed.latest_prompt_context()
                _assert(page_prompt_context is not None, "expected prompt context in first replay page")
                _assert(isinstance(page_prompt_context.prompt_cache_key, str) and bool(page_prompt_context.prompt_cache_key), "expected prompt cache key")
                _assert(any(fragment.kind == "environment_context" for fragment in page_prompt_context.fragments), "expected environment fragment in prompt context")

                typed_from_sdk = await client.events.list_typed(response_id, include_model_events=False)
                _assert(any(item.type == "anyagent.done" for item in typed_from_sdk), f"expected typed done in sdk list: {typed_from_sdk}")
                sdk_prompt_context = await client.events.latest_prompt_context(response_id)
                _assert(sdk_prompt_context is not None, "expected sdk latest_prompt_context result")
                _assert(sdk_prompt_context.prompt_cache_key == page_prompt_context.prompt_cache_key, "sdk prompt cache key mismatch")
                _assert(sdk_prompt_context.fragment_count >= sdk_prompt_context.retained_fragment_count >= 1, "expected compacted fragment stats")
                replay_summary = await client.events.replay_summary(response_id)
                _assert(replay_summary.done is True, f"expected replay summary done flag: {replay_summary}")
                _assert(replay_summary.prompt_context is not None, "expected replay summary prompt context")
                _assert(replay_summary.prompt_context.prompt_cache_key == sdk_prompt_context.prompt_cache_key, "replay summary prompt cache key mismatch")
                _assert(replay_summary.typed_event_count >= 2, f"expected typed replay events: {replay_summary}")
        finally:
            server_app.get_default_model_provider = original_provider

    print("ok: acceptance_prompt_context_sdk_smoke")


def main() -> int:
    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
