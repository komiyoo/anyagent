from __future__ import annotations

"""Offline smoke for exec output truncation + meta propagation."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from anyagent.server.app import create_app


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


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
  resources:
    output_max_bytes: 12
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
        app = create_app(
            workspace_dir=root,
            api_key="user-key",
            admin_api_key="admin-key",
            sandbox_root_dir=root / ".sandbox",
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10.0) as client:
            resp = await client.post(
                "/internal/tools/execute",
                headers={"Authorization": "Bearer admin-key"},
                json={
                    "agent_id": "main",
                    "session_key": "sess-trunc",
                    "response_id": "resp-trunc",
                    "tool_call_id": "call-trunc",
                    "tool_name": "exec",
                    "arguments_json": {
                        "cmd": "printf abcdefghijklmnopqrstuvwxyz",
                        "timeout": 5,
                    },
                    "context": {},
                },
            )
            _assert(resp.status_code == 200, f"unexpected status: {resp.status_code} {resp.text}")
            payload = resp.json()
            _assert(payload["status"] == "completed", f"expected completed: {payload}")
            _assert(payload["meta"]["output_truncated"] is True, f"meta output_truncated mismatch: {payload}")

            result = json.loads(payload["output"])
            stdout_bytes = result["stdout"].encode("utf-8")
            stderr_bytes = result["stderr"].encode("utf-8")
            _assert(result["output_truncated"] is True, f"payload output_truncated mismatch: {result}")
            _assert(len(stdout_bytes) + len(stderr_bytes) <= 12, f"truncated bytes exceed limit: {result}")
            _assert(result["stdout"] == "abcdefghijkl", f"unexpected stdout after truncation: {result}")

    print("ok: acceptance_exec_output_truncation_smoke")


def main() -> int:
    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
