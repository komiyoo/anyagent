from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import httpx
from openai.types.responses.response import Response

from anyagent.server.app import create_app
from anyagent.storage.external import apply_external_storage_schema_async, resolve_external_sql_backend_config


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("test agent\n", encoding="utf-8")
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


async def _run_mysql_builtin_smoke(*, mysql_dsn: str, redis_dsn: str) -> None:
    await apply_external_storage_schema_async(
        config=resolve_external_sql_backend_config(
            postgres_dsn=None,
            mysql_dsn=mysql_dsn,
            redis_dsn=redis_dsn,
            schema_name=None,
            namespace="anyagent",
            dialect="mysql",
        )
    )

    with tempfile.TemporaryDirectory(prefix="anyagent-mysql-builtin-") as td:
        root = Path(td)
        _write_workspace(root)

        class _FakeProvider:
            async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
                _ = body, idempotency_key, timeout_s
                return Response.model_validate(
                    {
                        "id": "resp_mysql_builtin_1",
                        "object": "response",
                        "created_at": 1,
                        "model": "gpt-4o-mini",
                        "output": [],
                        "parallel_tool_calls": False,
                        "tool_choice": "none",
                        "tools": [],
                        "status": "completed",
                    }
                )

        import anyagent.server.app as app_mod

        app_mod.get_default_model_provider = lambda: _FakeProvider()
        os.environ["STORAGE_MODE"] = "external"
        os.environ["SQL_BACKEND_DIALECT"] = "mysql"
        os.environ["MYSQL_DSN"] = mysql_dsn
        os.environ["REDIS_DSN"] = redis_dsn

        app = create_app(
            workspace_dir=root,
            api_key="user-key",
            admin_api_key="admin-key",
            sandbox_root_dir=root / ".sandbox",
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10.0) as client:
            resp = await client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer user-key"},
                json={
                    "model": "gpt-4o-mini",
                    "input": "hello mysql",
                    "metadata": {"session_key": "mysql-builtin"},
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(f"/v1/responses failed: {resp.status_code} {resp.text}")
            payload = resp.json()
            if payload.get("status") != "completed":
                raise RuntimeError(f"unexpected final status: {payload}")


def main() -> int:
    mysql_dsn = (os.getenv("ANYAGENT_TEST_MYSQL_DSN") or "").strip()
    if not mysql_dsn:
        print("skip: mysql builtin smoke (set ANYAGENT_TEST_MYSQL_DSN to enable; use a dedicated test database)")
        return 0
    redis_dsn = (os.getenv("ANYAGENT_TEST_REDIS_DSN") or os.getenv("REDIS_DSN") or "").strip()
    if not redis_dsn:
        print("skip: mysql builtin smoke (set ANYAGENT_TEST_REDIS_DSN or REDIS_DSN to enable)")
        return 0
    asyncio.run(_run_mysql_builtin_smoke(mysql_dsn=mysql_dsn, redis_dsn=redis_dsn))
    print("ok: acceptance_mysql_builtin_server_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
