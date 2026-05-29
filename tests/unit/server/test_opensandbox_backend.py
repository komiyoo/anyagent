from __future__ import annotations

import asyncio
import json

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from anyagent.protocol.sandbox import FileSystemSandboxPolicy, NetworkSandboxPolicy, ResourceLimits, SandboxPolicy
from anyagent.server.sandbox.opensandbox_backend import OpenSandboxWorkspaceBackend


def _mock_opensandbox_app() -> FastAPI:
    app = FastAPI()
    sandboxes: set[str] = set()
    fail_diagnostics = {"value": False}
    app.state.fail_diagnostics = fail_diagnostics
    app.state.create_payloads = []
    app.state.command_payloads = []

    @app.post("/sandboxes")
    async def create_sandbox(request: Request) -> JSONResponse:
        app.state.create_payloads.append(await request.json())
        sandboxes.add("sandbox-1")
        return JSONResponse(
            {
                "id": "sandbox-1",
                "image": {"uri": "ubuntu:24.04"},
                "status": {"state": "Running", "reason": "Ready", "message": "sandbox ready"},
            },
            status_code=202,
        )

    @app.get("/sandboxes/{sandbox_id}")
    async def get_sandbox(sandbox_id: str) -> JSONResponse:
        if sandbox_id not in sandboxes:
            raise HTTPException(status_code=404, detail="sandbox not found")
        if fail_diagnostics["value"]:
            raise HTTPException(status_code=405, detail="diagnostics disabled")
        return JSONResponse(
            {
                "id": sandbox_id,
                "image": {"uri": "ubuntu:24.04"},
                "status": {"state": "Running", "reason": "Ready", "message": "sandbox ready"},
            }
        )

    @app.get("/sandboxes/{sandbox_id}/endpoints/{port}")
    async def get_endpoint(request: Request, sandbox_id: str, port: int) -> JSONResponse:
        if sandbox_id not in sandboxes:
            raise HTTPException(status_code=404, detail="sandbox not found")
        endpoint = str(request.base_url).removeprefix("http://").rstrip("/") + f"/sandboxes/{sandbox_id}/proxy/{port}"
        return JSONResponse({"endpoint": endpoint})

    @app.get("/sandboxes/{sandbox_id}/proxy/44772/ping")
    async def ping_proxy(sandbox_id: str) -> Response:
        if sandbox_id not in sandboxes:
            raise HTTPException(status_code=404, detail="sandbox not found")
        return Response(status_code=200)

    @app.post("/sandboxes/{sandbox_id}/proxy/44772/command")
    async def run_command(sandbox_id: str, body: dict[str, object]) -> Response:
        if sandbox_id not in sandboxes:
            raise HTTPException(status_code=404, detail="sandbox not found")
        app.state.command_payloads.append(dict(body))
        text = str(body.get("command") or "")
        if "fail" in text:
            events = [
                {"type": "stderr", "text": "bad\n"},
                {"type": "error", "error": {"ename": "CommandExecError", "evalue": "exit status 7"}},
                {"type": "execution_complete", "execution_time": 5},
            ]
        else:
            events = [
                {"type": "stdout", "text": "ok\n"},
                {"type": "execution_complete", "execution_time": 3},
            ]
        payload = "\n\n".join(json.dumps(event) for event in events) + "\n\n"
        return Response(content=payload, media_type="text/event-stream")

    return app


def test_opensandbox_workspace_backend_executes_command_and_reports_diagnostics() -> None:
    async def _run() -> None:
        backend = OpenSandboxWorkspaceBackend(
            base_url="http://mock",
            api_key="secret",
            workspace_root="/workspace",
            image="ubuntu:24.04",
            sandbox_timeout_s=3600,
            cpu_limit="1000m",
            memory_limit="1Gi",
        )
        await backend._client.aclose()
        mock_app = _mock_opensandbox_app()
        backend._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app), base_url="http://mock")
        policy = SandboxPolicy(
            mode="opensandbox",
            network=NetworkSandboxPolicy(
                enabled=False,
                allow_hosts=["example.com"],
                deny_hosts=["metadata.google.internal"],
            ),
            filesystem=FileSystemSandboxPolicy(
                persistence_mode="session_hot_cold",
                workspace_root="/workspace/project",
                hot_idle_ttl_s=30,
                cold_retention_s=3600,
                max_snapshot_bytes=4096,
            ),
            resource_limits=ResourceLimits(
                cpu_cores=0.5,
                memory_mb=256,
                disk_mb=1024,
                output_max_bytes=128,
            ),
            ttl_seconds=120,
        )
        try:
            result = await backend.execute_command(
                policy=policy,
                agent_id="main",
                session_key="s1",
                cmd="printf ok",
                workdir=None,
                timeout_seconds=10,
            )
            assert result.exit_code == 0
            assert result.stdout == "ok\n"
            assert result.cwd == "/workspace/project"
            create_payload = mock_app.state.create_payloads[0]
            assert create_payload["timeout"] == 120
            assert create_payload["resourceLimits"] == {
                "cpu": "500m",
                "memory": "256Mi",
                "disk": "1024Mi",
            }
            assert create_payload["env"] == {
                "HOME": "/workspace/project/home",
                "TMPDIR": "/workspace/project/tmp",
            }
            assert create_payload["metadata"]["network_enabled"] == "false"
            assert create_payload["metadata"]["network_allow_hosts"] == '["example.com"]'
            assert create_payload["metadata"]["network_deny_hosts"] == '["metadata.google.internal"]'
            assert create_payload["metadata"]["output_max_bytes"] == "128"
            assert create_payload["metadata"]["filesystem_persistence_mode"] == "session_hot_cold"
            assert create_payload["metadata"]["filesystem_hot_idle_ttl_s"] == "30"
            assert create_payload["metadata"]["filesystem_cold_retention_s"] == "3600"
            assert create_payload["metadata"]["filesystem_max_snapshot_bytes"] == "4096"
            assert create_payload["entrypoint"][-1].startswith("mkdir -p /workspace/project ")
            assert mock_app.state.command_payloads[0]["cwd"] == "/workspace/project"
            assert mock_app.state.command_payloads[0]["timeout"] == 10000

            failed = await backend.execute_command(
                policy=policy,
                agent_id="main",
                session_key="s1",
                cmd="fail",
                workdir="subdir",
                timeout_seconds=10,
            )
            assert failed.exit_code == 7
            assert failed.stderr == "bad\nexit status 7"
            assert failed.cwd == "/workspace/project/subdir"

            ref = await backend.get_workspace(agent_id="main", session_key="s1")
            assert ref is not None
            assert ref.sandbox_id == "sandbox-1"
            diagnostics = await backend.get_runtime_diagnostics(agent_id="main", session_key="s1", record=ref)
            assert diagnostics is not None
            assert diagnostics.provider == "opensandbox"
            assert diagnostics.sandbox_id == "sandbox-1"
            assert diagnostics.state == "Running"

            mock_app.state.fail_diagnostics["value"] = True
            cached = await backend.get_runtime_diagnostics(agent_id="main", session_key="s1", record=ref)
            assert cached is not None
            assert cached.provider == "opensandbox"
            assert cached.sandbox_id == "sandbox-1"
        finally:
            await backend.aclose()

    asyncio.run(_run())
