from __future__ import annotations

"""Offline smoke for Tool Runtime credential injection."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from anyagent.server.app import create_app
from anyagent.tool_runtime.models import ToolDefinition


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
        app = create_app(
            workspace_dir=root,
            api_key="user-key",
            admin_api_key="admin-key",
            sandbox_root_dir=root / ".sandbox",
        )

        async def _handler(arguments: dict, context: dict) -> str:
            _ = arguments
            return context.get("_credentials", {}).get("header:Authorization", "")

        app.state.anyagent.runtime._registry.register_tool(  # noqa: SLF001
            ToolDefinition(
                name="core.auth_echo",
                description="Echo injected auth header",
                category="core",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                credentials=[
                    {
                        "ref_kind": "bearer_token",
                        "injection_target": "header:Authorization",
                        "format": "Bearer {value}",
                        "required": True,
                    }
                ],
            ),
            _handler,
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
            set_resp = await client.post(
                "/admin/credentials",
                headers={"Authorization": "Bearer admin-key"},
                json={
                    "credential_id": "cred_auth_echo",
                    "kind": "bearer_token",
                    "value": "secret-token",
                    "scope": {"level": "global"},
                    "metadata": {"provider": "test"},
                },
            )
            _assert(set_resp.status_code == 200, f"unexpected set status: {set_resp.status_code} {set_resp.text}")

            ok_resp = await client.post(
                "/internal/tools/execute",
                headers={"Authorization": "Bearer admin-key"},
                json={
                    "agent_id": "main",
                    "session_key": "sess-cred-ok",
                    "response_id": "resp-cred-ok",
                    "tool_call_id": "call-cred-ok",
                    "tool_name": "core.auth_echo",
                    "arguments_json": {},
                    "context": {"auth_ref": {"kind": "bearer_token", "ref": "cred_auth_echo"}},
                },
            )
            _assert(ok_resp.status_code == 200, f"unexpected execute status: {ok_resp.status_code} {ok_resp.text}")
            ok_payload = ok_resp.json()
            _assert(ok_payload["status"] == "completed", f"expected completed: {ok_payload}")
            _assert(ok_payload["output"] == "Bearer secret-token", f"injected output mismatch: {ok_payload}")

            missing_resp = await client.post(
                "/internal/tools/execute",
                headers={"Authorization": "Bearer admin-key"},
                json={
                    "agent_id": "main",
                    "session_key": "sess-cred-missing",
                    "response_id": "resp-cred-missing",
                    "tool_call_id": "call-cred-missing",
                    "tool_name": "core.auth_echo",
                    "arguments_json": {},
                    "context": {"auth_ref": {"kind": "bearer_token", "ref": "cred_missing"}},
                },
            )
            _assert(missing_resp.status_code == 200, f"unexpected missing status: {missing_resp.status_code} {missing_resp.text}")
            missing_payload = missing_resp.json()
            _assert(missing_payload["status"] == "error", f"expected error payload: {missing_payload}")
            _assert(missing_payload["error"]["code"] == "credential_not_found", f"unexpected error code: {missing_payload}")

            wrong_kind_resp = await client.post(
                "/internal/tools/execute",
                headers={"Authorization": "Bearer admin-key"},
                json={
                    "agent_id": "main",
                    "session_key": "sess-cred-wrong-kind",
                    "response_id": "resp-cred-wrong-kind",
                    "tool_call_id": "call-cred-wrong-kind",
                    "tool_name": "core.auth_echo",
                    "arguments_json": {},
                    "context": {"auth_ref": {"kind": "api_key", "ref": "cred_auth_echo"}},
                },
            )
            _assert(
                wrong_kind_resp.status_code == 200,
                f"unexpected wrong-kind status: {wrong_kind_resp.status_code} {wrong_kind_resp.text}",
            )
            wrong_kind_payload = wrong_kind_resp.json()
            _assert(wrong_kind_payload["status"] == "error", f"expected wrong-kind error payload: {wrong_kind_payload}")
            _assert(
                wrong_kind_payload["error"]["code"] == "credential_not_found",
                f"unexpected wrong-kind error code: {wrong_kind_payload}",
            )

    print("ok: acceptance_tool_credential_injection_smoke")


def main() -> int:
    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
