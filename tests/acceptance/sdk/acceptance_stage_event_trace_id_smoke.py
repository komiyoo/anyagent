from __future__ import annotations

"""Offline smoke for Stage Events trace_id propagation."""

import asyncio
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_created_event import ResponseCreatedEvent
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent import AnyAgent
import anyagent.server.routes.responses as server_app
from anyagent.server.app import create_app


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class _FakeProvider:
    def __init__(self) -> None:
        self._turn = 0

    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        model = str(body.get("model") or "gpt-4o-mini")
        if self._turn == 0:
            self._turn += 1
            payload = {
                "id": "resp_fake_trace",
                "object": "response",
                "created_at": int(time.time()),
                "model": model,
                "output": [
                    ResponseFunctionToolCall(
                        type="function_call",
                        call_id="call_exec_trace",
                        name="exec",
                        arguments=json.dumps({"cmd": "printf trace-ok", "timeout": 2}, ensure_ascii=False),
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
            }
            return Response.model_validate(payload)

        payload = {
            "id": "resp_fake_trace_followup",
            "object": "response",
            "created_at": int(time.time()),
            "model": model,
            "output": [
                ResponseOutputMessage(
                    id="msg_trace_done",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text="trace done", annotations=[])],
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
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\n", encoding="utf-8")
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
                sandbox_root_dir=root / ".sandbox",
            )

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as http:
                create_resp = await http.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer user-key"},
                    json={
                        "model": "gpt-4o-mini",
                        "input": "run trace test",
                        "metadata": {
                            "context": {
                                "trace": {
                                    "trace_id": "trace-smoke-1",
                                }
                            }
                        },
                    },
                )
                _assert(create_resp.status_code == 200, f"unexpected create status: {create_resp.status_code} {create_resp.text}")
                response_id = create_resp.json()["id"]

                client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
                seen_trace_ids: list[str] = []
                async for event in client.events.stream_typed(response_id, include_model_events=False):
                    if getattr(event, "type", None) == "anyagent.done":
                        break
                    if getattr(event, "type", "").startswith("anyagent.tool.") or getattr(event, "type", "").startswith("anyagent.command."):
                        seen_trace_ids.append(getattr(event, "trace_id", None))

                _assert(seen_trace_ids, "expected tool/command stage events")
                _assert(all(trace_id == "trace-smoke-1" for trace_id in seen_trace_ids), f"trace_ids mismatch: {seen_trace_ids}")
        finally:
            server_app.get_default_model_provider = original_provider

    print("ok: acceptance_stage_event_trace_id_smoke")


def main() -> int:
    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
