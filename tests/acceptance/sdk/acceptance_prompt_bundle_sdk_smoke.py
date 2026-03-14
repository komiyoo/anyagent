from __future__ import annotations

"""Offline smoke for AnyAgent client prompt bundle preview helpers."""

import asyncio
import time
from pathlib import Path

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent import AnyAgent
from anyagent.server.app import create_app


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class _RecordingProvider:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        self.bodies.append(dict(body))
        payload = {
            "id": "resp_prompt_bundle_sdk",
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
    workspace_agents = root / "AGENTS.md"
    workspace_agents.write_text("这是 workspace 级指令。\n", encoding="utf-8")
    agent_dir = root / ".agents" / "agents" / "main"
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
    (agent_dir / "mcp.json").write_text(
        """
{
  "mcpServers": {
    "github": {
      "url": "https://mcp.example.test"
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )


async def _run(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    provider = _RecordingProvider()

    import anyagent.server.app as app_mod

    original = app_mod.get_default_model_provider
    original_manifest = app_mod.resolve_manifest_with_mcp
    app_mod.get_default_model_provider = lambda: provider
    async def _fake_manifest(**kwargs):
        _ = kwargs
        return ([{"type": "function", "name": "exec", "description": "Execute a shell command.", "parameters": {"type": "object"}}], 1)
    app_mod.resolve_manifest_with_mcp = _fake_manifest
    try:
        app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
            preview = await client.prompts.preview(
                {
                    "model": "gpt-5",
                    "input": "hello",
                    "stream": False,
                    "metadata": {"session_key": "sess_prompt_bundle_sdk"},
                }
            )
            _assert(preview.agent_id == "main", f"unexpected agent_id: {preview}")
            _assert("exec" in preview.manifest_tool_names, f"missing exec manifest tool: {preview}")
            _assert("github" in preview.mcp_servers, f"missing mcp server: {preview}")
            _assert(any(item.kind == "sandbox_guidance" for item in preview.rendered_fragments), f"missing sandbox guidance: {preview}")
            _assert(any(item.kind == "mcp_server_ref" for item in preview.rendered_fragments), f"missing mcp ref: {preview}")
            _assert(
                any("<sandbox_guidance>" in item.rendered_text for item in preview.rendered_fragments),
                f"missing sandbox guidance text: {preview}",
            )
            _assert(
                any("<mcp_server_ref>" in item.rendered_text for item in preview.rendered_fragments),
                f"missing mcp ref text: {preview}",
            )
            example = client.prompts.example_run_bundle(scenario="multi_skill_research")
            _assert(example.scenario == "multi_skill_research", f"scenario mismatch: {example}")
            _assert(len(example.prompt_bundle.selected_skill_ids) >= 2, f"expected multi-skill example: {example}")
            _assert(len(example.prompt_bundle.mcp_servers) >= 2, f"expected multiple mcp refs: {example}")
            _assert(any("PromptEnvelope" in step.detail for step in example.explanation.steps), f"missing explanation detail: {example}")
            catalog = client.prompts.example_scenarios()
            _assert(any(item.label == "Toolset Refresh Retry" for item in catalog), f"missing scenario catalog label: {catalog}")
    finally:
        app_mod.get_default_model_provider = original
        app_mod.resolve_manifest_with_mcp = original_manifest


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="anyagent-prompt-bundle-sdk-") as td:
        asyncio.run(_run(Path(td)))
    print("ok: acceptance_prompt_bundle_sdk_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
