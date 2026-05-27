from __future__ import annotations

"""Offline smoke for credential set/delete audit logging."""

import asyncio
import io
import logging
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

        logger = logging.getLogger("anyagent.credentials")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
                set_resp = await client.post(
                    "/admin/credentials",
                    headers={"Authorization": "Bearer admin-key"},
                    json={
                        "credential_id": "cred_audit_test",
                        "kind": "bearer_token",
                        "value": "super-secret-value",
                        "scope": {"level": "global"},
                        "metadata": {"display_name": "Audit Test"},
                    },
                )
                _assert(set_resp.status_code == 200, f"unexpected set status: {set_resp.status_code} {set_resp.text}")
                delete_resp = await client.delete(
                    "/admin/credentials/cred_audit_test",
                    headers={"Authorization": "Bearer admin-key"},
                )
                _assert(delete_resp.status_code == 200, f"unexpected delete status: {delete_resp.status_code} {delete_resp.text}")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

        logs = stream.getvalue()
        _assert("credential_audit" in logs, f"missing credential audit logs: {logs}")
        _assert("\"operation\":\"set\"" in logs, f"missing set audit event: {logs}")
        _assert("\"operation\":\"delete\"" in logs, f"missing delete audit event: {logs}")
        _assert("\"credential_id\":\"cred_audit_test\"" in logs, f"missing credential id: {logs}")
        _assert("cred_aud_" in logs, f"missing audit_ref: {logs}")
        _assert("super-secret-value" not in logs, f"secret leaked in logs: {logs}")

    print("ok: acceptance_credential_audit_smoke")


def main() -> int:
    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
