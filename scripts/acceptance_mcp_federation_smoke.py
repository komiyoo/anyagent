from __future__ import annotations

"""
Acceptance smoke: MCP federation wiring in Agent API/SDK (offline, no real MCP server).

This smoke validates:
- Agent Pack `mcp.json` loading (and per-agent scoping)
- Skill dependency mapping for `transport: mcp`
- MCP manager tool merge + `mcp.<label>.<tool>` call routing
- SDK-side manifest merge helper (`resolve_manifest_with_mcp`)
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


def _bootstrap_repo_imports() -> None:
    """Adds `packages/anyagent/src` to import path when running from repo root."""
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "packages" / "anyagent" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_bootstrap_repo_imports()

from anyagent.agent_packs import load_agent_catalog
from anyagent.agent_runtime.tool_loop import resolve_manifest_with_mcp
from anyagent.mcp.manager import MCPServerManager
from anyagent.mcp.models import MCPConfig
from anyagent.skills.dependencies import requested_tool_names_for_skill
from anyagent.skills.models import SkillFrontMatter, SkillPackage


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


def _smoke_agent_pack_mcp_loading() -> None:
    """Validates optional `mcp.json` loading for one agent pack."""
    with tempfile.TemporaryDirectory(prefix="anyagent_mcp_pack_") as td:
        ws = Path(td)
        agent_dir = ws / ".agents" / "agents" / "main"
        agent_dir.mkdir(parents=True, exist_ok=True)

        (agent_dir / "agent.yaml").write_text(
            "\n".join(
                [
                    "exposed: true",
                    "tools:",
                    "  requested_tool_names: [\"core.web_fetch\"]",
                    "skills: {}",
                ]
            ),
            encoding="utf-8",
        )
        (agent_dir / "AGENTS.md").write_text("# test\n", encoding="utf-8")
        (agent_dir / "mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "amap": {"url": "https://mcp.amap.com/mcp?key=example"},
                        "local-fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
                    }
                }
            ),
            encoding="utf-8",
        )

        catalog = load_agent_catalog(workspace_dir=ws)
        pack = catalog.get("main")
        _assert(pack is not None, "agent pack main should exist")
        _assert(pack.mcp_config is not None, "mcp_config should be loaded from mcp.json")
        _assert(pack.mcp_config.mcpServers["amap"].infer_transport().value == "streamable_http", "url transport infer failed")
        _assert(pack.mcp_config.mcpServers["local-fs"].infer_transport().value == "stdio", "command transport infer failed")


def _smoke_skill_mcp_dependency_mapping() -> None:
    """Validates `transport: mcp` dependencies map to `mcp.<label>.*` patterns."""
    skill = SkillPackage(
        skill_dir=Path("/tmp/skill"),
        skill_md_path=Path("/tmp/skill/SKILL.md"),
        scope="agent",
        frontmatter=SkillFrontMatter(name="mcp-skill", description="test"),
        body_markdown="",
        agent_metadata={
            "dependencies": {
                "tools": [
                    {"transport": "mcp", "value": "github"},
                ]
            }
        },
    )
    names = requested_tool_names_for_skill(skill)
    _assert(names == ["mcp.github.*"], f"unexpected mcp dependency mapping: {names}")


class _FakeMCPServer:
    """In-memory fake server used to validate manager routing without network."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.connected = False

    async def ensure_connected(self) -> None:
        self.connected = True

    async def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "sum",
                "description": "sum two numbers",
                "inputSchema": {
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                    "required": ["a", "b"],
                },
            }
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "sum":
            return {"content": [{"type": "text", "text": "not-found"}], "is_error": True}
        value = float(arguments.get("a", 0)) + float(arguments.get("b", 0))
        return {"content": [{"type": "text", "text": str(value)}], "is_error": False}

    async def disconnect(self) -> None:
        self.connected = False

    def is_idle(self, now: float) -> bool:
        return False


async def _smoke_manager_merge_and_call() -> None:
    """Validates MCP manager tool conversion + qualified call routing."""
    cfg = MCPConfig.model_validate({"mcpServers": {"calc": {"url": "https://example.com/mcp"}}})
    manager = MCPServerManager(agent_id="main", mcp_config=cfg)
    manager._servers = {"calc": _FakeMCPServer("calc")}  # type: ignore[assignment]

    try:
        tools = await manager.list_all_tools()
        names = [t.get("name") for t in tools]
        _assert("mcp.calc.sum" in names, f"mcp tool namespace conversion failed: {names}")

        output = await manager.call_tool("mcp.calc.sum", {"a": 1, "b": 2})
        _assert("3.0" in output, f"unexpected mcp call output: {output}")
    finally:
        await manager.cleanup()


class _FakeManifestTool:
    """Minimal tool runtime manifest tool shape for helper testing."""

    def __init__(self, name: str) -> None:
        self._name = name

    def model_dump(self, exclude_none: bool = True, by_alias: bool = True) -> dict[str, Any]:
        return {"type": "function", "name": self._name, "description": "", "parameters": {"type": "object", "properties": {}}}


class _FakeManifestResp:
    """Minimal tool runtime manifest response shape for helper testing."""

    def __init__(self) -> None:
        self.tools = [_FakeManifestTool("core.web_fetch")]
        self.toolset_version = 7


class _FakeToolRuntimeClient:
    """Minimal ToolRuntime client stub used for manifest merge smoke."""

    async def manifest(self, req: Any) -> _FakeManifestResp:
        return _FakeManifestResp()


class _FakeMCPManager:
    """Minimal MCP manager stub used for SDK helper smoke."""

    async def list_all_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "mcp.calc.sum",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            }
        ]


async def _smoke_sdk_manifest_merge() -> None:
    """Validates SDK manifest helper merges Tool Runtime tools with MCP tools."""
    tools, version = await resolve_manifest_with_mcp(
        tool_runtime=_FakeToolRuntimeClient(),  # type: ignore[arg-type]
        mcp_manager=_FakeMCPManager(),  # type: ignore[arg-type]
        agent_id="main",
        session_key="smoke",
        metadata={"context": {}},
        request_tools=None,
        enabled_skills=None,
    )
    names = {t.get("name") for t in tools if isinstance(t, dict)}
    _assert(version == 7, f"unexpected toolset_version: {version}")
    _assert("core.web_fetch" in names, "missing Tool Runtime manifest tool")
    _assert("mcp.calc.sum" in names, "missing MCP merged tool")


async def main() -> int:
    """Runs MCP federation smoke checks."""
    _smoke_agent_pack_mcp_loading()
    _smoke_skill_mcp_dependency_mapping()
    await _smoke_manager_merge_and_call()
    await _smoke_sdk_manifest_merge()
    print("ok: acceptance_mcp_federation_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
