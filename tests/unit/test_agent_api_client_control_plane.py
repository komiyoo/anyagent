from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from anyagent import AnyAgent
from anyagent.server.app import create_app
from anyagent.tool_runtime import create_tool_runtime_app


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
  mode: disabled
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_sdk_health_and_admin_credentials_match_server(tmp_path: Path) -> None:
    asyncio.run(_run_sdk_health_and_admin_credentials_match_server(tmp_path))


def test_sdk_admin_plugin_catalog_matches_tool_runtime(tmp_path: Path) -> None:
    asyncio.run(_run_sdk_admin_plugin_catalog_matches_tool_runtime(tmp_path))


def test_sdk_admin_skill_update_helpers_match_server(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_sdk_admin_skill_update_helpers_match_server(tmp_path, monkeypatch))


async def _run_sdk_health_and_admin_credentials_match_server(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="user-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)

        health = await client.health()
        assert health.ok is True
        assert health.workspace == str(tmp_path.resolve())
        assert health.agent_ids == ["main"]

        ref = await client.admin.set_credential(
            {
                "credential_id": "search_api_key",
                "kind": "api_key",
                "value": "secret-value",
                "scope": {"level": "agent", "agent_id": "main"},
                "metadata": {"provider": "search"},
            }
        )
        assert ref.credential_id == "search_api_key"
        assert ref.scope.level == "agent"
        assert ref.scope.agent_id == "main"

        listed = await client.admin.list_credentials()
        assert len(listed.credentials) == 1
        assert listed.credentials[0].credential_id == "search_api_key"

        deleted = await client.admin.delete_credential("search_api_key")
        assert deleted == {"ok": True, "deleted": True, "credential_id": "search_api_key"}

        listed_after = await client.admin.list_credentials()
        assert listed_after.credentials == []


async def _run_sdk_admin_plugin_catalog_matches_tool_runtime(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    agent_yaml = tmp_path / ".agents" / "agents" / "main" / "agent.yaml"
    agent_yaml.write_text(
        """
exposed: true
tools:
  requested_tool_names:
    - demo.echo
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
    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        """
{
  "plugin_id": "demo",
  "description": "Demo connector.",
  "channels": ["demo"],
  "entrypoint": "plugin.py:register",
  "docs": ["README.md"],
  "schemas": ["schemas/config.schema.json"],
  "tests": ["tests/smoke.py"]
}
""".lstrip(),
        encoding="utf-8",
    )
    (plugin_dir / "README.md").write_text("# Demo connector\n", encoding="utf-8")
    (plugin_dir / "schemas").mkdir()
    (plugin_dir / "schemas" / "config.schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
    (plugin_dir / "tests").mkdir()
    (plugin_dir / "tests" / "smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        """
from anyagent.tool_runtime.models import ToolDefinition

async def echo(args, context):
    return args["text"]

def register(api):
    api.registerTool(
        ToolDefinition(
            name="demo.echo",
            description="Echo text.",
            category="channel",
            kind="command",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
        ),
        echo,
    )
""".lstrip(),
        encoding="utf-8",
    )

    app = create_tool_runtime_app(
        workspace_dir=tmp_path,
        internal_key="internal-key",
        admin_api_key="admin-key",
        plugin_roots=["plugins"],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        catalog = await client.admin.plugin_catalog()

        assert catalog.plugin_roots == [str(tmp_path / "plugins")]
        assert catalog.errors == []
        assert len(catalog.loaded) == 1
        loaded = catalog.loaded[0]
        assert loaded.plugin_id == "demo"
        assert loaded.description == "Demo connector."
        assert loaded.channels == ["demo"]
        assert loaded.plugin_dir == str(plugin_dir)
        assert loaded.tools[0].name == "demo.echo"
        assert loaded.tools[0].category == "channel"
        assert loaded.cite == {
            "manifest": str(plugin_dir / "plugin.json"),
            "entrypoint": str(plugin_dir / "plugin.py"),
        }
        assert loaded.docs == [str(plugin_dir / "README.md")]
        assert loaded.schemas == [str(plugin_dir / "schemas" / "config.schema.json")]
        assert loaded.tests == [str(plugin_dir / "tests" / "smoke.py")]


async def _run_sdk_admin_skill_update_helpers_match_server(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, cwd: str, **_: object) -> object:
        calls.append(cmd)
        skill_dir = Path(cwd) / ".agents" / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        version = "v1" if len(calls) == 1 else "v2"
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: demo-skill\ndescription: Demo skill\n---\n\nregistry {version}\n",
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("anyagent.server.app.subprocess.run", fake_run)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        installed = await client.admin.install_agent_skill(
            "main",
            {"channel": "skills.sh", "package": "demo/package", "skill": "demo-skill"},
        )
        assert installed.name == "demo-skill"

        check = await client.admin.check_agent_skill_update("main", "demo-skill")
        assert check.agent_id == "main"
        assert check.directory_name == "demo-skill"
        assert check.updatable is True
        assert check.update_available is True
        assert check.current_hash != check.latest_hash

        applied = await client.admin.apply_agent_skill_update("main", "demo-skill")
        assert applied.name == "demo-skill"
        assert "registry v2" in (tmp_path / ".agents" / "agents" / "main" / "skills" / "demo-skill" / "SKILL.md").read_text(
            encoding="utf-8"
        )
