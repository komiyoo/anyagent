from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from anyagent.protocol.credential_vault import CredentialScope
from anyagent.protocol.tool_runtime import AuthRef, ExecuteRequest, ManifestRequest, ToolContext
from anyagent.server.sandbox import WorkspaceRuntimeConfig, build_workspace_runtime
from anyagent.server.security.credential_backends import FileBackend, InfisicalBackend, InfisicalBackendConfig
from anyagent.server.security.credential_backends import EnvBackend
from anyagent.tool_runtime import ToolRuntimeClient, create_tool_runtime_app, create_tool_runtime_app_async
from anyagent.tool_runtime.settings import ToolRuntimeSettings, build_tool_runtime_server_config


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names:",
                "    - exec",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: local-unsafe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_session_workspace(root: Path) -> None:
    _write_workspace(root)
    (root / ".anyagent" / "agents" / "main" / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names:",
                "    - exec",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: local-unsafe",
                "  filesystem:",
                "    persistence_mode: session_hot_cold",
                "    workspace_root: /workspace",
                "    hot_idle_ttl_s: 60",
                "    cold_retention_s: 3600",
                "    max_snapshot_bytes: 1048576",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_web_fetch_workspace(root: Path) -> None:
    _write_workspace(root)
    (root / ".anyagent" / "agents" / "main" / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names:",
                "    - core.web_fetch",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_standalone_tool_runtime_serves_manifest_execute_and_list(tmp_path: Path) -> None:
    asyncio.run(_run_standalone_tool_runtime_serves_manifest_execute_and_list(tmp_path))


def test_standalone_tool_runtime_can_use_core_file_write_backend(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_BACKEND", "file-write")
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_FILE_ROOT", ".anyagent/credentials")
    app = create_tool_runtime_app(workspace_dir=tmp_path)
    backend = app.state.anyagent_tool_runtime._credential_store
    assert isinstance(backend, FileBackend)


def test_tool_runtime_settings_build_server_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_RUNTIME_INTERNAL_KEY", " internal-key ")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key")
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_BACKEND", "file-write")
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_FILE_ROOT", ".anyagent/credentials")
    monkeypatch.setenv("TOOL_RUNTIME_PLUGIN_ROOTS", "plugins/a, plugins/b")
    monkeypatch.setenv("TOOL_RUNTIME_PLUGINS_FAIL_OPEN", "1")
    monkeypatch.setenv("WORKSPACE_EVENT_BACKEND", "jsonl")
    monkeypatch.setenv("WORKSPACE_EVENT_ROOT_DIR", "events")
    monkeypatch.setenv("WORKSPACE_EVENT_MAX_BUFFER", "42")
    monkeypatch.setenv("ALLOW_SANDBOX", "1")
    monkeypatch.setenv("SANDBOX_BACKEND", "local_reference")
    monkeypatch.setenv("SANDBOX_ISOLATION_MODE", "local_unsafe")
    monkeypatch.setenv("SANDBOX_FILESYSTEM_PERSISTENCE_MODE", "session_hot_cold")
    monkeypatch.setenv("WORKSPACE_METADATA_BACKEND", "local_file")
    monkeypatch.setenv("WORKSPACE_METADATA_ROOT_DIR", "metadata")
    monkeypatch.setenv("WORKSPACE_LEASE_BACKEND", "memory")
    monkeypatch.setenv("WORKSPACE_SNAPSHOT_BACKEND", "local_file")
    monkeypatch.setenv("WORKSPACE_SNAPSHOT_ROOT_DIR", "snapshots")

    config = build_tool_runtime_server_config(ToolRuntimeSettings(), workspace_dir=tmp_path)

    assert config.workspace_dir == tmp_path
    assert config.internal_key == "internal-key"
    assert config.admin_api_key == "admin-key"
    assert config.plugin_roots == ("plugins/a", "plugins/b")
    assert config.plugins_fail_open is True
    assert config.workspace_event_backend == "jsonl"
    assert config.workspace_event_root_dir == "events"
    assert config.workspace_event_max_buffer == 42
    assert config.credential.backend == "file-write"
    assert config.credential.workspace_dir == tmp_path
    assert config.workspace_runtime.allow_sandbox is True
    assert config.workspace_runtime.sandbox_backend == "local_reference"
    assert config.workspace_runtime.sandbox_isolation_mode == "local_unsafe"
    assert config.workspace_runtime.sandbox_filesystem_persistence_mode == "session_hot_cold"
    assert config.workspace_runtime.workspace_metadata_backend == "local_file"
    assert config.workspace_runtime.workspace_metadata_root_dir == "metadata"
    assert config.workspace_runtime.workspace_snapshot_backend == "local_file"
    assert config.workspace_runtime.workspace_snapshot_root_dir == "snapshots"


def test_tool_runtime_settings_import_does_not_import_server_package() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import anyagent.tool_runtime.settings; print('anyagent.server' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "False"


def test_tool_runtime_app_loads_workspace_env_before_settings(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.delenv("MCP_CREDENTIAL_STORE_BACKEND", raising=False)
    monkeypatch.delenv("MCP_CREDENTIAL_STORE_FILE_ROOT", raising=False)
    (tmp_path / ".env").write_text(
        "MCP_CREDENTIAL_STORE_BACKEND=file-write\nMCP_CREDENTIAL_STORE_FILE_ROOT=.anyagent/credentials\n",
        encoding="utf-8",
    )

    try:
        app = create_tool_runtime_app(workspace_dir=tmp_path)
        backend = app.state.anyagent_tool_runtime._credential_store
        assert isinstance(backend, FileBackend)
    finally:
        monkeypatch.delenv("MCP_CREDENTIAL_STORE_BACKEND", raising=False)
        monkeypatch.delenv("MCP_CREDENTIAL_STORE_FILE_ROOT", raising=False)


def test_standalone_tool_runtime_admin_credentials_manage_file_backend(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_standalone_tool_runtime_admin_credentials_manage_file_backend(tmp_path, monkeypatch))


def test_standalone_tool_runtime_admin_credentials_reject_read_only_backend(tmp_path: Path) -> None:
    asyncio.run(_run_standalone_tool_runtime_admin_credentials_reject_read_only_backend(tmp_path))


def test_standalone_tool_runtime_loads_plugins_from_core_loader(tmp_path: Path) -> None:
    asyncio.run(_run_standalone_tool_runtime_loads_plugins_from_core_loader(tmp_path))


def test_standalone_tool_runtime_admin_sandbox_workspace_lifecycle(tmp_path: Path) -> None:
    asyncio.run(_run_standalone_tool_runtime_admin_sandbox_workspace_lifecycle(tmp_path))


def test_standalone_tool_runtime_persists_workspace_events_jsonl(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_EVENT_BACKEND", "jsonl")
    monkeypatch.setenv("WORKSPACE_EVENT_ROOT_DIR", str(tmp_path / "workspace-events"))
    asyncio.run(_run_standalone_tool_runtime_persists_workspace_events_jsonl(tmp_path))


def test_standalone_tool_runtime_serves_core_web_fetch_with_credentials(tmp_path: Path) -> None:
    asyncio.run(_run_standalone_tool_runtime_serves_core_web_fetch_with_credentials(tmp_path))


def test_standalone_tool_runtime_uses_workspace_runtime_cross_instance_recovery(tmp_path: Path) -> None:
    asyncio.run(_run_standalone_tool_runtime_uses_workspace_runtime_cross_instance_recovery(tmp_path))


def test_standalone_tool_runtime_async_builder_uses_workspace_runtime_config(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_standalone_tool_runtime_async_builder_uses_workspace_runtime_config(tmp_path, monkeypatch))


async def _run_standalone_tool_runtime_serves_manifest_execute_and_list(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    app = create_tool_runtime_app(workspace_dir=tmp_path, internal_key="internal-key", sandbox_root_dir=tmp_path / ".sandbox")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        unauthorized = await http.post("/internal/tools/manifest", json={"agent_id": "main"})
        assert unauthorized.status_code == 401, unauthorized.text

        client = ToolRuntimeClient(base_url="http://testserver", internal_key="internal-key", http=http)
        manifest = await client.manifest(
            ManifestRequest(
                agent_id="main",
                session_key="sess-1",
                requested_tool_names=["exec"],
                context=ToolContext(),
            )
        )
        assert [tool.name for tool in manifest.tools] == ["exec"]

        listed = await http.get("/internal/tools/list", headers={"Authorization": "Bearer internal-key"})
        assert listed.status_code == 200, listed.text
        assert [tool["name"] for tool in listed.json()["tools"]] == [
            "admin.credential_set",
            "core.web_fetch",
            "core.web_search",
            "exec",
        ]

        executed = await client.execute(
            ExecuteRequest(
                agent_id="main",
                session_key="sess-1",
                response_id="resp_1",
                tool_call_id="call_1",
                tool_name="exec",
                arguments_json={"cmd": "printf hello", "workdir": "work", "timeout": 2},
                toolset_version=manifest.toolset_version,
                context=ToolContext(),
            )
        )
        assert executed.status == "completed"
        output = json.loads(executed.output)
        assert output["stdout"] == "hello"


async def _run_standalone_tool_runtime_serves_core_web_fetch_with_credentials(tmp_path: Path) -> None:
    _write_web_fetch_workspace(tmp_path)
    store = EnvBackend()
    await store.set(
        credential_id="cred_web_fetch",
        kind="bearer_token",
        value="secret-token",
        scope=CredentialScope(level="global"),
    )
    app = create_tool_runtime_app(
        workspace_dir=tmp_path,
        internal_key="internal-key",
        credential_store=store,
    )
    transport = httpx.ASGITransport(app=app)
    seen: dict[str, object] = {}

    async def _fake_get(url: str, *, headers: dict[str, str]) -> object:
        seen["url"] = url
        seen["headers"] = dict(headers)
        return SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/plain"},
            text="ok",
            url=url,
        )

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = ToolRuntimeClient(base_url="http://testserver", internal_key="internal-key", http=http)
        manifest = await client.manifest(
            ManifestRequest(
                agent_id="main",
                session_key="sess-1",
                requested_tool_names=["core.web_fetch"],
                context=ToolContext(),
            )
        )
        assert [tool.name for tool in manifest.tools] == ["core.web_fetch"]

        with patch("httpx.AsyncClient.get", side_effect=_fake_get):
            executed = await client.execute(
                ExecuteRequest(
                    agent_id="main",
                    session_key="sess-1",
                    response_id="resp_web_fetch",
                    tool_call_id="call_web_fetch",
                    tool_name="core.web_fetch",
                    arguments_json={"url": "https://example.com/private"},
                    toolset_version=manifest.toolset_version,
                    context=ToolContext(auth_ref=AuthRef(kind="bearer_token", ref="cred_web_fetch")),
                )
            )

    assert executed.status == "completed"
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["user-agent"] == "anyagent/0"
    payload = json.loads(executed.output)
    assert payload["status"] == 200
    assert payload["text"] == "ok"


async def _run_standalone_tool_runtime_uses_workspace_runtime_cross_instance_recovery(tmp_path: Path) -> None:
    _write_session_workspace(tmp_path)
    metadata_root = tmp_path / "metadata"
    snapshot_root = tmp_path / "snapshots"

    workspace_runtime_1 = await build_workspace_runtime(
        WorkspaceRuntimeConfig(
            allow_sandbox=True,
            sandbox_isolation_mode="local_unsafe",
            sandbox_root_dir=str(tmp_path / "sandbox-1"),
            sandbox_filesystem_persistence_mode="session_hot_cold",
            workspace_metadata_backend="local_file",
            workspace_metadata_root_dir=str(metadata_root),
            workspace_snapshot_backend="local_file",
            workspace_snapshot_root_dir=str(snapshot_root),
            workspace_lease_backend="memory",
        )
    )
    app1 = create_tool_runtime_app(
        workspace_dir=tmp_path,
        internal_key="internal-key",
        admin_api_key="admin-key",
        workspace_runtime=workspace_runtime_1,
    )
    async with app1.router.lifespan_context(app1):
        transport = httpx.ASGITransport(app=app1)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            client = ToolRuntimeClient(base_url="http://testserver", internal_key="internal-key", http=http)
            manifest = await client.manifest(
                ManifestRequest(
                    agent_id="main",
                    session_key="sess-cross-instance",
                    requested_tool_names=["exec"],
                    context=ToolContext(),
                )
            )
            executed = await client.execute(
                ExecuteRequest(
                    agent_id="main",
                    session_key="sess-cross-instance",
                    response_id="resp_cross_instance_a",
                    tool_call_id="call_cross_instance_a",
                    tool_name="exec",
                    arguments_json={"cmd": "printf cross-instance-core > cross.txt", "timeout": 2},
                    toolset_version=manifest.toolset_version,
                    context=ToolContext(),
                )
            )
            assert executed.status == "completed"
            hibernated = await http.post(
                "/admin/sandbox/workspace/hibernate",
                headers={"Authorization": "Bearer admin-key"},
                json={"agent_id": "main", "session_key": "sess-cross-instance"},
            )
            assert hibernated.status_code == 200, hibernated.text
            assert hibernated.json()["state"] == "hibernated"

    workspace_runtime_2 = await build_workspace_runtime(
        WorkspaceRuntimeConfig(
            allow_sandbox=True,
            sandbox_isolation_mode="local_unsafe",
            sandbox_root_dir=str(tmp_path / "sandbox-2"),
            sandbox_filesystem_persistence_mode="session_hot_cold",
            workspace_metadata_backend="local_file",
            workspace_metadata_root_dir=str(metadata_root),
            workspace_snapshot_backend="local_file",
            workspace_snapshot_root_dir=str(snapshot_root),
            workspace_lease_backend="memory",
        )
    )
    app2 = create_tool_runtime_app(
        workspace_dir=tmp_path,
        internal_key="internal-key",
        admin_api_key="admin-key",
        workspace_runtime=workspace_runtime_2,
    )
    async with app2.router.lifespan_context(app2):
        transport = httpx.ASGITransport(app=app2)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            client = ToolRuntimeClient(base_url="http://testserver", internal_key="internal-key", http=http)
            manifest = await client.manifest(
                ManifestRequest(
                    agent_id="main",
                    session_key="sess-cross-instance",
                    requested_tool_names=["exec"],
                    context=ToolContext(),
                )
            )
            executed = await client.execute(
                ExecuteRequest(
                    agent_id="main",
                    session_key="sess-cross-instance",
                    response_id="resp_cross_instance_b",
                    tool_call_id="call_cross_instance_b",
                    tool_name="exec",
                    arguments_json={"cmd": "cat cross.txt", "timeout": 2},
                    toolset_version=manifest.toolset_version,
                    context=ToolContext(),
                )
            )
            assert executed.status == "completed"
            assert "cross-instance-core" in json.loads(executed.output)["stdout"]


async def _run_standalone_tool_runtime_async_builder_uses_workspace_runtime_config(tmp_path: Path, monkeypatch) -> None:
    _write_session_workspace(tmp_path)
    monkeypatch.setenv("ALLOW_SANDBOX", "1")
    monkeypatch.setenv("SANDBOX_ISOLATION_MODE", "local_unsafe")
    monkeypatch.setenv("SANDBOX_FILESYSTEM_PERSISTENCE_MODE", "session_hot_cold")
    monkeypatch.setenv("WORKSPACE_METADATA_BACKEND", "local_file")
    monkeypatch.setenv("WORKSPACE_METADATA_ROOT_DIR", str(tmp_path / "metadata"))
    monkeypatch.setenv("WORKSPACE_SNAPSHOT_BACKEND", "local_file")
    monkeypatch.setenv("WORKSPACE_SNAPSHOT_ROOT_DIR", str(tmp_path / "snapshots"))

    app = await create_tool_runtime_app_async(
        workspace_dir=tmp_path,
        internal_key="internal-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / "sandbox",
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            health = await http.get("/admin/sandbox/health", headers={"Authorization": "Bearer admin-key"})
            assert health.status_code == 200, health.text
            payload = health.json()
            assert payload["enabled"] is True
            assert payload["metadata_backend"] == "local_file"
            assert payload["snapshot_backend"] == "local_file"
            assert payload["persistence_mode"] == "session_hot_cold"


async def _run_standalone_tool_runtime_admin_sandbox_workspace_lifecycle(tmp_path: Path) -> None:
    _write_session_workspace(tmp_path)
    sandbox_root = tmp_path / ".sandbox"
    app = create_tool_runtime_app(
        workspace_dir=tmp_path,
        internal_key="internal-key",
        admin_api_key="admin-key",
        sandbox_root_dir=sandbox_root,
    )
    transport = httpx.ASGITransport(app=app)
    auth = {"Authorization": "Bearer admin-key"}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        unauthorized = await http.get("/admin/sandbox/health")
        assert unauthorized.status_code == 401

        health_before = await http.get("/admin/sandbox/health", headers=auth)
        assert health_before.status_code == 200, health_before.text
        assert health_before.json() == {
            "enabled": True,
            "backend": "local_unsafe",
            "metadata_backend": "local_reference",
            "lease_backend": "none",
            "snapshot_backend": "local_reference",
            "sandbox_mode": "local-unsafe",
            "persistence_mode": "session_hot_cold",
            "workspace_root": "/workspace",
            "workspace_count": 0,
            "sandbox_root_dir": str(sandbox_root.resolve()),
            "runtime_providers": [],
            "runtime_states": {},
        }

        client = ToolRuntimeClient(base_url="http://testserver", internal_key="internal-key", http=http)
        manifest = await client.manifest(
            ManifestRequest(
                agent_id="main",
                session_key="sess-workspace",
                requested_tool_names=["exec"],
                context=ToolContext(),
            )
        )
        executed = await client.execute(
            ExecuteRequest(
                agent_id="main",
                session_key="sess-workspace",
                response_id="resp_workspace",
                tool_call_id="call_workspace",
                tool_name="exec",
                arguments_json={"cmd": "printf workspace-admin > hello.txt", "timeout": 2},
                toolset_version=manifest.toolset_version,
                context=ToolContext(),
            )
        )
        assert executed.status == "completed"

        list_resp = await http.get("/admin/sandbox/workspaces", headers=auth)
        assert list_resp.status_code == 200, list_resp.text
        workspaces = list_resp.json()["workspaces"]
        assert len(workspaces) == 1
        assert workspaces[0]["session_partition_key"] == "main::sess-workspace"
        assert workspaces[0]["runtime_diagnostics"] == {
            "provider": "local_unsafe",
            "sandbox_id": "local:main__sess-workspace",
            "state": "active",
        }

        get_resp = await http.get(
            "/admin/sandbox/workspace",
            headers=auth,
            params={"agent_id": "main", "session_key": "sess-workspace"},
        )
        assert get_resp.status_code == 200, get_resp.text
        assert get_resp.json()["state"] == "active"

        hibernate_resp = await http.post(
            "/admin/sandbox/workspace/hibernate",
            headers=auth,
            json={"agent_id": "main", "session_key": "sess-workspace"},
        )
        assert hibernate_resp.status_code == 200, hibernate_resp.text
        hibernated = hibernate_resp.json()
        assert hibernated["state"] == "hibernated"
        assert hibernated["generation"] == 1
        assert hibernated["runtime_diagnostics"] == {
            "provider": "local_unsafe",
            "state": "hibernated",
        }
        assert isinstance(hibernated["snapshot_uri"], str) and hibernated["snapshot_uri"]

        events_resp = await http.get(
            "/admin/sandbox/events",
            headers=auth,
            params={"agent_id": "main", "session_key": "sess-workspace", "limit": 10},
        )
        assert events_resp.status_code == 200, events_resp.text
        events = events_resp.json()["events"]
        assert [item["seq"] for item in events] == [1, 2, 3]
        assert [item["type"] for item in events] == [
            "anyagent.sandbox.workspace.checkpointing",
            "anyagent.sandbox.workspace.checkpointed",
            "anyagent.sandbox.workspace.hibernated",
        ]
        assert all(item["session_partition_key"] == "main::sess-workspace" for item in events)

        health_after = await http.get("/admin/sandbox/health", headers=auth)
        assert health_after.status_code == 200, health_after.text
        assert health_after.json()["workspace_count"] == 1
        assert health_after.json()["runtime_providers"] == ["local_unsafe"]
        assert health_after.json()["runtime_states"] == {"hibernated": 1}

        delete_resp = await http.delete(
            "/admin/sandbox/workspace",
            headers=auth,
            params={"agent_id": "main", "session_key": "sess-workspace"},
        )
        assert delete_resp.status_code == 200, delete_resp.text
        assert delete_resp.json() == {"ok": True, "deleted": True}

        missing = await http.get(
            "/admin/sandbox/workspace",
            headers=auth,
            params={"agent_id": "main", "session_key": "sess-workspace"},
        )
        assert missing.status_code == 404


async def _run_standalone_tool_runtime_persists_workspace_events_jsonl(tmp_path: Path) -> None:
    _write_session_workspace(tmp_path)
    event_root = tmp_path / "workspace-events"
    auth = {"Authorization": "Bearer admin-key"}
    for sandbox_root in (tmp_path / "sandbox-1", tmp_path / "sandbox-2"):
        app = create_tool_runtime_app(
            workspace_dir=tmp_path,
            internal_key="internal-key",
            admin_api_key="admin-key",
            sandbox_root_dir=sandbox_root,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            client = ToolRuntimeClient(base_url="http://testserver", internal_key="internal-key", http=http)
            manifest = await client.manifest(
                ManifestRequest(
                    agent_id="main",
                    session_key="sess-jsonl",
                    requested_tool_names=["exec"],
                    context=ToolContext(),
                )
            )
            executed = await client.execute(
                ExecuteRequest(
                    agent_id="main",
                    session_key="sess-jsonl",
                    response_id=f"resp_{sandbox_root.name}",
                    tool_call_id=f"call_{sandbox_root.name}",
                    tool_name="exec",
                    arguments_json={"cmd": f"printf {sandbox_root.name} > marker.txt", "timeout": 2},
                    toolset_version=manifest.toolset_version,
                    context=ToolContext(),
                )
            )
            assert executed.status == "completed"
            hibernate_resp = await http.post(
                "/admin/sandbox/workspace/hibernate",
                headers=auth,
                json={"agent_id": "main", "session_key": "sess-jsonl"},
            )
            assert hibernate_resp.status_code == 200, hibernate_resp.text
            events_resp = await http.get(
                "/admin/sandbox/events",
                headers=auth,
                params={"agent_id": "main", "session_key": "sess-jsonl", "limit": 20},
            )
            assert events_resp.status_code == 200, events_resp.text
            assert len(events_resp.json()["events"]) == (3 if sandbox_root.name == "sandbox-1" else 6)

    files = list(event_root.rglob("workspace-events.jsonl"))
    assert len(files) == 1
    lines = [line for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 6


async def _run_standalone_tool_runtime_loads_plugins_from_core_loader(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    agent_yaml = tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml"
    agent_yaml.write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names:",
                "    - demo.echo",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "demo",
                "description": "Demo connector.",
                "channels": ["demo"],
                "entrypoint": "plugin.py:register",
                "docs": ["README.md"],
                "schemas": ["schemas/config.schema.json"],
                "tests": ["tests/smoke.py"],
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "README.md").write_text("# Demo connector\n", encoding="utf-8")
    (plugin_dir / "schemas").mkdir()
    (plugin_dir / "schemas" / "config.schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
    (plugin_dir / "tests").mkdir()
    (plugin_dir / "tests" / "smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from anyagent.tool_runtime.models import ToolDefinition",
                "",
                "async def echo(args, context):",
                "    return args['text']",
                "",
                "def register(api):",
                "    api.registerTool(",
                "        ToolDefinition(",
                "            name='demo.echo',",
                "            description='Echo text.',",
                "            category='channel',",
                "            kind='command',",
                "            parameters={",
                "                'type': 'object',",
                "                'additionalProperties': False,",
                "                'required': ['text'],",
                "                'properties': {'text': {'type': 'string'}},",
                "            },",
                "        ),",
                "        echo,",
                "    )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    app = create_tool_runtime_app(workspace_dir=tmp_path, internal_key="internal-key", admin_api_key="admin-key", plugin_roots=["plugins"])
    assert app.state.anyagent_tool_runtime_loaded_plugins[0]["plugin_id"] == "demo"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        catalog_unauthorized = await http.get("/admin/plugins/catalog")
        assert catalog_unauthorized.status_code == 401
        catalog = await http.get("/admin/plugins/catalog", headers={"Authorization": "Bearer admin-key"})
        assert catalog.status_code == 200, catalog.text
        catalog_payload = catalog.json()
        assert catalog_payload["plugin_roots"] == [str(tmp_path / "plugins")]
        assert catalog_payload["errors"] == []
        assert catalog_payload["loaded"] == [
            {
                "plugin_id": "demo",
                "description": "Demo connector.",
                "channels": ["demo"],
                "plugin_dir": str(plugin_dir),
                "entrypoint": "plugin.py:register",
                "tools": [
                    {
                        "name": "demo.echo",
                        "category": "channel",
                        "kind": "command",
                        "description": "Echo text.",
                    }
                ],
                "cite": {
                    "manifest": str(plugin_dir / "plugin.json"),
                    "entrypoint": str(plugin_dir / "plugin.py"),
                },
                "docs": [str(plugin_dir / "README.md")],
                "schemas": [str(plugin_dir / "schemas" / "config.schema.json")],
                "tests": [str(plugin_dir / "tests" / "smoke.py")],
            }
        ]

        listed = await http.get("/internal/tools/list", headers={"Authorization": "Bearer internal-key"})
        assert listed.status_code == 200, listed.text
        assert [tool["name"] for tool in listed.json()["tools"]] == [
            "admin.credential_set",
            "core.web_fetch",
            "core.web_search",
            "demo.echo",
            "exec",
        ]

        client = ToolRuntimeClient(base_url="http://testserver", internal_key="internal-key", http=http)
        manifest = await client.manifest(
            ManifestRequest(
                agent_id="main",
                session_key="sess-1",
                requested_tool_names=["demo.echo"],
                context=ToolContext(),
            )
        )
        assert [tool.name for tool in manifest.tools] == ["demo.echo"]

        executed = await client.execute(
            ExecuteRequest(
                agent_id="main",
                session_key="sess-1",
                response_id="resp_plugin",
                tool_call_id="call_plugin",
                tool_name="demo.echo",
                arguments_json={"text": "hello-plugin"},
                toolset_version=manifest.toolset_version,
                context=ToolContext(),
            )
        )
        assert executed.status == "completed"
        assert executed.output == "hello-plugin"


async def _run_standalone_tool_runtime_admin_credentials_manage_file_backend(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_BACKEND", "file-write")
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_FILE_ROOT", ".anyagent/credentials")
    app = create_tool_runtime_app(workspace_dir=tmp_path, admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        disabled = create_tool_runtime_app(workspace_dir=tmp_path)
        disabled_transport = httpx.ASGITransport(app=disabled)
        async with httpx.AsyncClient(transport=disabled_transport, base_url="http://disabled") as disabled_http:
            disabled_resp = await disabled_http.get("/admin/credentials")
            assert disabled_resp.status_code == 404

        unauthorized = await http.get("/admin/credentials")
        assert unauthorized.status_code == 401

        auth = {"Authorization": "Bearer admin-key"}
        capabilities_resp = await http.get("/admin/credentials/capabilities", headers=auth)
        assert capabilities_resp.status_code == 200, capabilities_resp.text
        assert capabilities_resp.json()["secret_value_returned"] is False

        set_resp = await http.post(
            "/admin/credentials",
            headers=auth,
            json={
                "credential_id": "cred_api",
                "kind": "bearer_token",
                "value": "secret",
                "scope": {"level": "agent", "agent_id": "main"},
                "metadata": {"provider": "test"},
            },
        )
        assert set_resp.status_code == 200, set_resp.text
        assert set_resp.json()["metadata"] == {"provider": "test"}

        list_resp = await http.get("/admin/credentials", headers=auth)
        assert list_resp.status_code == 200, list_resp.text
        assert list_resp.json()["credentials"] == [
            {
                "credential_id": "cred_api",
                "kind": "bearer_token",
                "scope": {"level": "agent", "agent_id": "main"},
                "metadata": {"provider": "test"},
            }
        ]

        delete_resp = await http.delete("/admin/credentials/cred_api", headers=auth)
        assert delete_resp.status_code == 200, delete_resp.text
        assert delete_resp.json() == {"ok": True, "deleted": True, "credential_id": "cred_api"}


async def _run_standalone_tool_runtime_admin_credentials_reject_read_only_backend(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    backend = InfisicalBackend(
        config=InfisicalBackendConfig(
            host="https://app.infisical.test",
            client_id="client-id",
            client_secret="client-secret",
            project_id="project-id",
            environment="dev",
            credential_root_path="/anyagent/credentials",
        ),
        client_factory=lambda **_: None,
    )
    app = create_tool_runtime_app(workspace_dir=tmp_path, admin_api_key="admin-key", credential_store=backend)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.post(
            "/admin/credentials",
            headers={"Authorization": "Bearer admin-key"},
            json={
                "credential_id": "cred_api",
                "kind": "bearer_token",
                "value": "secret",
                "scope": {"level": "global"},
                "metadata": {},
            },
        )
        assert resp.status_code == 501, resp.text
